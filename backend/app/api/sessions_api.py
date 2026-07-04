"""Replay session endpoints (doc §8): create, step, clock-clipped bars with
overlays, restart, dispose. Seek stays lesson-only and is rejected here."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import sessions
from app.analysis.indicators import ema_series
from app.api import deps
from app.api.serialize import bar_json, day_meta, point_json
from app.marketdata.calendar import CalendarUnavailable
from app.marketdata.fetcher import NotTradingDay
from app.marketdata.window import BarWindow
from app.detectors.engine import build_snapshot
from app.grading.grader import GradeResult, grade_entry, tier_at_least
from app.models import to_db_ts
from app.providers.base import ProviderError
from app.sim.engine import OrderError, SimEngine, SimOrder
from app.sim.sizing import SizingError, size_position
from app.stores import journal

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateSessionIn(BaseModel):
    symbol: str
    day: date
    lookback: int = Field(default=3, ge=0, le=10)
    start: str = Field(default="open", pattern="^(open|session_open)$")


def _get(session_id: str) -> sessions.Session:
    try:
        return sessions.get_session(session_id)
    except sessions.SessionNotFound:
        raise HTTPException(status_code=404, detail="no such session")


def _window(request: Request, session: sessions.Session) -> BarWindow:
    return BarWindow(
        deps.get_db(request),
        deps.get_calendar(request),
        session.clock,
        session.day,
        lookback_days=session.lookback_days,
    )


def _info(session: sessions.Session) -> dict:
    return {
        "id": session.id,
        "mode": session.mode,
        "symbols": session.symbols,
        "day": session.day.isoformat(),
        "clock": int(session.clock.current.timestamp()),
        "done": session.done,
        "start_at": int(session.start_at.timestamp()),
        "end_at": int(session.end_at.timestamp()),
    }


@router.post("/sessions")
def create_session(body: CreateSessionIn, request: Request) -> dict:
    symbol = body.symbol.upper()
    fetcher = deps.get_fetcher(request)
    if fetcher is not None:
        try:
            fetcher.ensure_day(symbol, body.day)  # lazy fetch + lookback (doc §5)
        except NotTradingDay:
            raise HTTPException(status_code=404, detail=f"{body.day} is not a trading day")
        except (ProviderError, CalendarUnavailable) as e:
            logger.warning("lazy fetch failed for %s %s: %s", symbol, body.day, e)
    cfg = deps.get_cfg(request)
    try:
        session = sessions.create_session(
            deps.get_calendar(request),
            [symbol],
            body.day,
            lookback_days=body.lookback,
            start=body.start,
            sim=SimEngine(cfg.starting_balance, cfg.intraday_leverage),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _info(session)


def _persist_new_trades(request: Request, session: sessions.Session) -> None:
    """Write-through: closed trades land in the journal as they happen."""
    if session.sim is None:
        return
    conn = deps.get_db(request)
    closed = [t for t in session.sim.trades if t.closed]
    for trade in closed[session.persisted_trades :]:
        journal.insert_closed_trade(conn, session.sim.mode, session.day, trade)
    session.persisted_trades = len(closed)


@router.post("/sessions/{session_id}/step")
def step(session_id: str, request: Request, bars: int = 1) -> dict:
    session = _get(session_id)
    result = sessions.step_session(session, _window(request, session), bars)
    _persist_new_trades(request, session)
    return {
        "clock": int(result.clock.timestamp()),
        "cutoff": int(result.cutoff.timestamp()),
        "done": result.done,
        "events": result.events,
        "new_bars": {sym: [bar_json(b) for b in bs] for sym, bs in result.new_bars.items()},
    }


@router.get("/sessions/{session_id}/bars")
def session_bars(
    session_id: str, request: Request, symbol: str | None = None, tf: str = "5m"
) -> dict:
    session = _get(session_id)
    sym = (symbol or session.symbols[0]).upper()
    window = _window(request, session)
    agg = window.bars(sym, tf)
    closes = [b.close for b in agg]
    times = [b.ts for b in agg]
    return {
        "symbol": sym,
        "tf": tf,
        "day": session.day.isoformat(),
        "clock": int(session.clock.current.timestamp()),
        "done": session.done,
        "bars": [bar_json(b) for b in agg],
        "days": [day_meta(d) for d in window.days],
        "overlays": {
            "vwap": point_json(window.vwap(sym)),
            "ema9": point_json(list(zip(times, ema_series(closes, 9)))),
            "ema20": point_json(list(zip(times, ema_series(closes, 20)))),
        },
        "rvol": window.rvol(sym),
        "sma200": window.sma200(sym),
    }


@router.get("/sessions/{session_id}/state")
def state(session_id: str) -> dict:
    return _info(_get(session_id))


@router.post("/sessions/{session_id}/restart")
def restart(session_id: str, request: Request) -> dict:
    session = _get(session_id)
    sessions.restart_session(session)
    if session.sim is not None:  # restart-the-day = fresh account (doc §8)
        cfg = deps.get_cfg(request)
        session.sim = SimEngine(cfg.starting_balance, cfg.intraday_leverage)
        session.persisted_trades = 0
    return _info(session)


# ------------------------------------------------------------------ sim API


class OrderIn(BaseModel):
    kind: str = Field(default="bracket", pattern="^(bracket|market|limit|stop)$")
    side: str = Field(pattern="^(buy|sell)$")
    qty: int | None = Field(default=None, ge=1)
    entry_type: str = Field(default="market", pattern="^(market|limit)$")
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    risk_pct: float | None = Field(default=None, gt=0, le=10)


def _order_json(order: SimOrder) -> dict:
    return {
        "id": order.id,
        "symbol": order.symbol,
        "side": order.side,
        "type": order.type,
        "qty": order.qty,
        "limit_price": order.limit_price,
        "stop_price": order.stop_price,
        "bracket_id": order.bracket_id,
        "role": order.role,
        "status": order.status,
        "fill_price": order.fill_price,
        "reason": order.reason,
    }


@router.post("/sessions/{session_id}/orders")
def place_order(session_id: str, body: OrderIn, request: Request) -> dict:
    session = _get(session_id)
    sim = session.sim
    if sim is None:
        raise HTTPException(status_code=409, detail="this session has no sim account")
    cfg = deps.get_cfg(request)
    symbol = session.symbols[0]
    now = session.clock.current
    grade = None
    with session.lock:
        if body.kind == "bracket":
            if body.stop_price is None or body.target_price is None:
                raise HTTPException(status_code=400, detail="bracket needs stop_price and target_price")
            entry_ref = body.limit_price or sim.last_close.get(symbol)
            if entry_ref is None:
                raise HTTPException(status_code=409, detail="no visible price yet — step at least one bar")
            qty = body.qty
            if qty is None:  # sizing calculator is the default path (doc §9)
                try:
                    qty = size_position(
                        sim.equity(), entry_ref, body.stop_price,
                        body.risk_pct or cfg.default_risk_pct, sim.leverage,
                    ).shares
                except SizingError as e:
                    raise HTTPException(status_code=400, detail=str(e))
            try:
                orders, events = sim.place_bracket(
                    now, symbol, body.side, qty,  # type: ignore[arg-type]
                    stop_price=body.stop_price, target_price=body.target_price,
                    entry_type=body.entry_type,  # type: ignore[arg-type]
                    limit_price=body.limit_price,
                )
            except OrderError as e:
                raise HTTPException(status_code=400, detail=str(e))
            if not any(e.kind == "reject" for e in events):
                grade = _grade_placement(
                    request, session,
                    "long" if body.side == "buy" else "short",
                    entry_ref, body.stop_price, body.target_price,
                )
        else:
            if body.qty is None:
                raise HTTPException(status_code=400, detail="qty required for non-bracket orders")
            order, events = sim.place_order(
                now, symbol, body.side, body.kind, body.qty,  # type: ignore[arg-type]
                limit_price=body.limit_price, stop_price=body.stop_price,
            )
            orders = [order]
    rejected = [e for e in events if e.kind == "reject"]
    return {
        "orders": [_order_json(o) for o in orders],
        "rejected": bool(rejected),
        "reason": rejected[0].detail if rejected else None,
        "grade": grade.to_json() if grade else None,
    }


def _grade_placement(
    request: Request,
    session: sessions.Session,
    direction: str,
    entry: float,
    stop: float | None,
    target: float | None,
) -> GradeResult | None:
    """Every graded-able entry gets its checklist at decision time (doc §10);
    graded lesson practice records the best tier on the session."""
    if stop is None:
        return None
    try:
        window = _window(request, session)
        snap = build_snapshot(window, session.symbols[0])
        rules = request.app.state.rules
        result = grade_entry(direction, entry, stop, target, snap, rules.get("grading", {}))
    except Exception as e:  # grading must never block a fill
        logger.warning("grading failed: %s", e)
        return None
    ctx = session.lesson_ctx
    if ctx is not None:
        if ctx.best_grade is None or not tier_at_least(ctx.best_grade, result.tier):
            ctx.best_grade = result.tier
    return result


@router.delete("/sessions/{session_id}/orders/{order_id}")
def cancel_order(session_id: str, order_id: int) -> dict:
    session = _get(session_id)
    if session.sim is None:
        raise HTTPException(status_code=409, detail="this session has no sim account")
    with session.lock:
        try:
            events = session.sim.cancel(order_id, session.clock.current)
        except OrderError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return {"events": [e.to_json() for e in events]}


@router.get("/sessions/{session_id}/account")
def account(session_id: str) -> dict:
    session = _get(session_id)
    sim = session.sim
    if sim is None:
        raise HTTPException(status_code=409, detail="this session has no sim account")
    return {
        "equity": round(sim.equity(), 2),
        "cash": round(sim.cash, 2),
        "buying_power_left": round(sim.buying_power_left(), 2),
        "flattened": sim.flattened,
        "positions": [
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_price": p.avg_price,
                "last": sim.last_close.get(p.symbol),
                "unrealized": round((sim.last_close.get(p.symbol, p.avg_price) - p.avg_price) * p.qty, 2),
                "initial_stop": p.initial_stop,
            }
            for p in sim.positions.values()
        ],
        "working_orders": [
            _order_json(o) for o in sim.orders.values() if o.status in ("working", "pending")
        ],
    }


@router.get("/sessions/{session_id}/trades")
def session_trades(session_id: str) -> dict:
    session = _get(session_id)
    sim = session.sim
    if sim is None:
        raise HTTPException(status_code=409, detail="this session has no sim account")
    return {
        "trades": [
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "qty": t.qty,
                "entry_ts": to_db_ts(t.entry_ts),
                "entry_price": t.entry_price,
                "exit_ts": to_db_ts(t.exit_ts) if t.exit_ts else None,
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "r_multiple": t.r_multiple,
            }
            for t in sim.trades
        ]
    }


class SizingIn(BaseModel):
    equity: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    risk_pct: float = Field(default=1.0, gt=0, le=10)
    leverage: float = Field(default=4.0, gt=0)


@router.post("/sizing")
def sizing(body: SizingIn) -> dict:
    try:
        s = size_position(body.equity, body.entry, body.stop, body.risk_pct, body.leverage)
    except SizingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "shares": s.shares,
        "risk_amount": round(s.risk_amount, 2),
        "per_share_risk": round(s.per_share_risk, 4),
        "notional": round(s.notional, 2),
        "bp_capped": s.bp_capped,
    }


class SeekIn(BaseModel):
    to: int  # epoch seconds, clamped to [start_at, end_at]


@router.post("/sessions/{session_id}/seek")
def seek(session_id: str, body: SeekIn) -> dict:
    session = _get(session_id)
    # Doc §8: no rewind in Practice — only scripted lesson steps may navigate.
    if session.mode != "lesson":
        raise HTTPException(
            status_code=403, detail="seek is available only inside scripted lesson steps"
        )
    sessions.seek_session(session, body.to)
    return _info(session)


@router.delete("/sessions/{session_id}")
def dispose(session_id: str) -> dict:
    sessions.delete_session(session_id)
    return {"deleted": session_id}
