"""Market Day endpoints (doc §11): live state + callout cards, acting on a
callout (graded at that moment), the morning briefing, and the EOD recap."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api import deps
from app.detectors.engine import build_snapshot
from app.grading.grader import grade_entry
from app.marketday.briefing import build_briefing, get_snapshot, save_snapshot
from app.marketday.poller import MarketDayPoller
from app.marketday.recap import build_recap
from app.marketdata.calendar import CalendarUnavailable
from app.marketdata.window import BarWindow
from app.models import ET, utcnow
from app.sim.sizing import SizingError, size_position

logger = logging.getLogger(__name__)
router = APIRouter()


def _poller(request: Request) -> MarketDayPoller:
    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(status_code=503, detail="market-day poller not running")
    return poller


@router.get("/marketday/state")
def marketday_state(request: Request) -> dict:
    poller = _poller(request)
    conn = deps.get_db(request)
    cal = deps.get_calendar(request)
    now = utcnow()
    try:
        state = cal.market_state(now)
        market = {"state": state.state, "display_day": state.display_day.isoformat()}
    except CalendarUnavailable as e:
        market = {"state": "unknown", "reason": str(e)}
    payload: dict = {
        "market": market,
        "poll": poller.status_json(),
        "trading_unlocked": poller.trading_unlocked(conn),
        "session": None,
        "callouts": [],
        "account": None,
    }
    session = poller.session
    if session is not None and poller.callouts is not None:
        clock = session.clock.now()
        sim = session.sim
        payload["session"] = {
            "day": session.day.isoformat(),
            "clock": int(clock.timestamp()),
            "delay_minutes": 15,
        }
        payload["callouts"] = poller.callouts.visible(clock)
        if sim is not None:
            payload["account"] = {
                "equity": round(sim.equity(), 2),
                "positions": [
                    {"symbol": p.symbol, "qty": p.qty, "avg_price": p.avg_price,
                     "unrealized": round((sim.last_close.get(p.symbol, p.avg_price) - p.avg_price) * p.qty, 2)}
                    for p in sim.positions.values()
                ],
                "flattened": sim.flattened,
            }
    return payload


class ActIn(BaseModel):
    risk_pct: float | None = Field(default=None, gt=0, le=10)


@router.post("/marketday/callouts/{callout_id}/act")
def act_on_callout(callout_id: str, request: Request, body: ActIn | None = None) -> dict:
    poller = _poller(request)
    conn = deps.get_db(request)
    cfg = deps.get_cfg(request)
    if not poller.trading_unlocked(conn):
        raise HTTPException(
            status_code=403,
            detail="trading in Market Day unlocks after Module 9 (risk management)",
        )
    session = poller.session
    engine = poller.callouts
    if session is None or engine is None or session.sim is None:
        raise HTTPException(status_code=409, detail="no live market-day session")
    callout = engine.callouts.get(callout_id)
    if callout is None:
        raise HTTPException(status_code=404, detail="no such callout")
    if callout.locked:
        raise HTTPException(status_code=403, detail="that setup is still locked")
    if not callout.tradeable:
        raise HTTPException(status_code=409, detail="informational signal — nothing to trade")
    if callout.status in ("acted", "expired"):
        raise HTTPException(status_code=409, detail=f"callout already {callout.status}")

    sig = callout.signal
    sim = session.sim
    clock = session.clock.now()
    window = BarWindow(conn, deps.get_calendar(request), session.clock, session.day, lookback_days=1)
    snap = build_snapshot(window, sig.symbol)
    # Grade the DECISION at this moment — acting on an invalidated setup is
    # Reckless with the reason (doc §11.3).
    user_grade = grade_entry(
        sig.direction, sig.entry, sig.stop, sig.target, snap,
        request.app.state.rules.get("grading", {}),
        setup_type=sig.setup_type,
        invalidated=callout.status == "invalidated",
    )
    entry_ref = sim.last_close.get(sig.symbol) or sig.entry
    try:
        qty = size_position(
            sim.equity(), entry_ref, sig.stop,
            (body.risk_pct if body and body.risk_pct else cfg.default_risk_pct),
            sim.leverage,
        ).shares
    except SizingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with session.lock:
        sim.pending_grades[sig.symbol] = user_grade.tier  # -> journal row
        orders, events = sim.place_bracket(
            clock, sig.symbol, "buy" if sig.direction == "long" else "sell", qty,
            stop_price=sig.stop, target_price=sig.target,
            setup_id=callout.setup_row_id,
        )
    rejected = [e for e in events if e.kind == "reject"]
    if rejected:
        raise HTTPException(status_code=409, detail=rejected[0].detail)
    engine.mark_acted(conn, callout, clock, user_grade)
    return {
        "orders": [o.id for o in orders],
        "qty": qty,
        "grade": user_grade.to_json(),
        "callout": callout.to_json(clock),
    }


@router.get("/briefing")
def briefing(request: Request, refresh: bool = False) -> dict:
    conn = deps.get_db(request)
    cal = deps.get_calendar(request)
    poller = _poller(request)
    now = utcnow()
    try:
        state = cal.market_state(now)
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    today = state.today
    if today is None:
        raise HTTPException(status_code=409, detail="no trading session today")
    existing = get_snapshot(conn, today.day.isoformat())
    if existing is not None and not refresh:
        return existing
    from app.marketday.poller import DelayedLiveClock

    cfg = deps.get_cfg(request)
    built = build_briefing(
        conn, cal, cfg.watchlist,
        poller.callouts.unlocked if poller.callouts else poller_unlocked(poller, conn),
        today, DelayedLiveClock(), now,
    )
    if existing is None:
        save_snapshot(conn, built)  # the snapshot EOD grades against (doc §11)
    return built


def poller_unlocked(poller: MarketDayPoller, conn) -> set[str]:
    return poller._unlocked(conn)  # noqa: SLF001 — same package family


@router.get("/recap")
def recap(request: Request, day: date | None = None) -> dict:
    conn = deps.get_db(request)
    cal = deps.get_calendar(request)
    cfg = deps.get_cfg(request)
    now = utcnow()
    if day is None:
        try:
            state = cal.market_state(now)
            candidate = cal.latest_on_or_before(now.astimezone(ET).date())
            if state.today is not None and now < state.today.close_utc():
                candidate = cal.prev_trading_day(state.today.day)  # today isn't over
            day = candidate.day
        except CalendarUnavailable as e:
            raise HTTPException(status_code=409, detail=str(e))
    if cal.day(day) is None:
        raise HTTPException(status_code=404, detail=f"{day} is not a trading day")
    return build_recap(conn, cal, request.app.state.rules, cfg.watchlist, day)
