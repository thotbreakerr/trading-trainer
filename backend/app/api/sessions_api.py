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
from app.providers.base import ProviderError

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
    try:
        session = sessions.create_session(
            deps.get_calendar(request),
            [symbol],
            body.day,
            lookback_days=body.lookback,
            start=body.start,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _info(session)


@router.post("/sessions/{session_id}/step")
def step(session_id: str, request: Request, bars: int = 1) -> dict:
    session = _get(session_id)
    result = sessions.step_session(session, _window(request, session), bars)
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
def restart(session_id: str) -> dict:
    session = _get(session_id)
    sessions.restart_session(session)
    return _info(session)


@router.post("/sessions/{session_id}/seek")
def seek(session_id: str) -> dict:
    _get(session_id)
    # Doc §8: no rewind in Practice — scripted lesson Watch steps get their own
    # navigation when the lesson engine lands.
    raise HTTPException(
        status_code=403, detail="seek is available only inside scripted lesson steps"
    )


@router.delete("/sessions/{session_id}")
def dispose(session_id: str) -> dict:
    sessions.delete_session(session_id)
    return {"deleted": session_id}
