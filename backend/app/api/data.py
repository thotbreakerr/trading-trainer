"""Data endpoints: calendar, market state, first-run backfill (doc §13)."""
from __future__ import annotations

import logging
import threading
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.api import deps
from app.config import AppConfig
from app.marketdata.calendar import CalendarUnavailable, MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.models import ET, utcnow
from app.providers.alpaca import AlpacaProvider

logger = logging.getLogger(__name__)
router = APIRouter()

_bf_lock = threading.Lock()
_bf_state: dict = {"state": "idle"}


@router.get("/calendar")
def calendar_range(start: date, end: date, request: Request) -> dict:
    cal = deps.get_calendar(request)
    try:
        cal.ensure_range(start, end)
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "days": [
            {
                "day": d.day.isoformat(),
                "open_et": d.open_et,
                "close_et": d.close_et,
                "session_open_et": d.session_open_et,
                "session_close_et": d.session_close_et,
                "half_day": d.is_half_day,
            }
            for d in cal.trading_days_between(start, end)
        ]
    }


@router.get("/market-state")
def market_state(request: Request) -> dict:
    cal = deps.get_calendar(request)
    now = utcnow()
    try:
        cal.ensure_around(now.astimezone(ET).date())
    except CalendarUnavailable:
        pass  # fall through: maybe already cached from an earlier run
    try:
        state = cal.market_state(now)
    except CalendarUnavailable as e:
        return {"state": "unknown", "reason": str(e)}
    return {
        "state": state.state,
        "display_day": state.display_day.isoformat(),
        "half_day": state.today.is_half_day if state.today else False,
    }


class BackfillIn(BaseModel):
    days_back: int | None = None


@router.post("/backfill")
def start_backfill(request: Request, body: BackfillIn | None = None) -> dict:
    cfg = deps.get_cfg(request)
    provider = deps.get_provider(request)
    if provider is None:
        raise HTTPException(status_code=409, detail="API keys not configured")
    days_back = (body.days_back if body and body.days_back else cfg.backfill_days)
    with _bf_lock:
        if _bf_state.get("state") == "running":
            raise HTTPException(status_code=409, detail="backfill already running")
        _bf_state.clear()
        _bf_state.update(
            {
                "state": "running",
                "current": None,
                "symbols_done": 0,
                "total_symbols": len(cfg.watchlist),
                "bars_added": 0,
                "errors": [],
            }
        )
    threading.Thread(
        target=_run_backfill, args=(cfg, provider, days_back), daemon=True
    ).start()
    return {"started": True, "days_back": days_back, "symbols": cfg.watchlist}


@router.get("/backfill/progress")
def backfill_progress() -> dict:
    with _bf_lock:
        return dict(_bf_state)


def _run_backfill(cfg: AppConfig, provider: AlpacaProvider, days_back: int) -> None:
    try:
        conn = db.get_conn(cfg.db_path)  # this thread's own connection
        calendar = MarketCalendar(conn, provider)
        fetcher = Fetcher(
            conn, provider, calendar, rvol_baseline_days=cfg.rvol_baseline_days
        )

        def on_progress(symbol: str, i: int, total: int) -> None:
            with _bf_lock:
                _bf_state.update({"current": symbol, "symbols_done": i})

        reports = fetcher.backfill(cfg.watchlist, days_back, on_progress)
        warnings = [w for r in reports for w in r.warnings]
        with _bf_lock:
            _bf_state.update(
                {
                    "state": "done",
                    "current": None,
                    "symbols_done": len(cfg.watchlist),
                    "bars_added": sum(r.bars_added for r in reports),
                    "errors": warnings,
                }
            )
    except Exception as e:  # surfaced via /backfill/progress, never silent
        logger.exception("backfill failed")
        with _bf_lock:
            _bf_state.update({"state": "error", "error": str(e)})
