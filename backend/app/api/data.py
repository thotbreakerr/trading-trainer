"""Data endpoints: calendar, market state, first-run backfill (doc §13)."""
from __future__ import annotations

import logging
import threading
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.analysis.indicators import ema_series
from app.api import deps
from app.api.serialize import bar_json, day_meta, point_json
from app.config import AppConfig
from app.detectors.engine import scan_day
from app.marketdata.aggregate import TF_MINUTES
from app.marketdata.calendar import CalendarUnavailable, MarketCalendar
from app.marketdata.fetcher import Fetcher, NotTradingDay
from app.marketdata.window import BarWindow, eod_clock
from app.models import ET, utcnow
from app.providers.alpaca import AlpacaProvider
from app.providers.base import ProviderError

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
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=f"Alpaca error: {e}")
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
    except (CalendarUnavailable, ProviderError) as e:
        # No keys / bad keys / API down: serve whatever calendar is cached.
        logger.warning("calendar refresh unavailable: %s", e)
    try:
        state = cal.market_state(now)
    except CalendarUnavailable as e:
        return {"state": "unknown", "reason": str(e)}
    return {
        "state": state.state,
        "display_day": state.display_day.isoformat(),
        "half_day": state.today.is_half_day if state.today else False,
    }


@router.get("/bars")
def get_bars(
    symbol: str, day: date, request: Request, tf: str = "5m", lookback: int = 3
) -> dict:
    """Completed-day bars for browsing: the requested day plus context
    lookback, lazily fetched (doc §5), served through the no-lookahead gate
    with an end-of-day clock."""
    if tf not in TF_MINUTES:
        raise HTTPException(status_code=400, detail=f"tf must be one of {sorted(TF_MINUTES)}")
    symbol = symbol.upper()
    lookback = max(0, min(lookback, 10))
    conn = deps.get_db(request)
    cal = deps.get_calendar(request)
    fetcher = deps.get_fetcher(request)
    if fetcher is not None:
        try:
            fetcher.ensure_day(symbol, day)
        except NotTradingDay:
            raise HTTPException(status_code=404, detail=f"{day} is not a trading day")
        except (ProviderError, CalendarUnavailable) as e:
            logger.warning("lazy fetch failed for %s %s: %s", symbol, day, e)
    cal_day = cal.day(day)
    if cal_day is None:
        raise HTTPException(
            status_code=404, detail=f"{day} is not a trading day (or calendar not cached)"
        )
    try:
        window = BarWindow(conn, cal, eod_clock(cal_day), day, lookback_days=lookback)
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    bars = window.bars(symbol, tf)
    closes = [b.close for b in bars]
    times = [b.ts for b in bars]
    return {
        "symbol": symbol,
        "tf": tf,
        "day": day.isoformat(),
        "bars": [bar_json(b) for b in bars],
        "days": [day_meta(d) for d in window.days],
        "overlays": {
            "vwap": point_json(window.vwap(symbol)),
            "ema9": point_json(list(zip(times, ema_series(closes, 9)))),
            "ema20": point_json(list(zip(times, ema_series(closes, 20)))),
        },
        "rvol": window.rvol(symbol),
    }


@router.get("/symbols")
def symbols(request: Request) -> dict:
    """Watchlist rail: last price + change vs prior close from cache.
    RVOL joins in with the indicator layer (replay engine phase)."""
    cfg = deps.get_cfg(request)
    conn = deps.get_db(request)
    cal = deps.get_calendar(request)
    now = utcnow()
    try:
        cal.ensure_around(now.astimezone(ET).date())
    except (CalendarUnavailable, ProviderError) as e:
        logger.warning("calendar refresh unavailable: %s", e)
    empty = [
        {"symbol": s, "last_price": None, "prior_close": None, "change_pct": None, "rvol": None}
        for s in cfg.watchlist
    ]
    try:
        state = cal.market_state(now)
    except CalendarUnavailable:
        return {"display_day": None, "state": "unknown", "symbols": empty}
    display = cal.day(state.display_day)
    items = []
    for entry in empty:
        sym = entry["symbol"]
        try:
            w = BarWindow(conn, cal, eod_clock(display), display.day, lookback_days=1)
            bars = w.bars_1m(sym)
            dailies = w.daily(sym, 1)
            if bars:
                entry["last_price"] = bars[-1].close
            if dailies:
                entry["prior_close"] = dailies[-1].close
            if entry["last_price"] is not None and entry["prior_close"]:
                entry["change_pct"] = (entry["last_price"] / entry["prior_close"] - 1.0) * 100
        except CalendarUnavailable:
            pass
        items.append(entry)
    return {
        "display_day": state.display_day.isoformat(),
        "state": state.state,
        "symbols": items,
    }


@router.get("/scan")
def scan(symbol: str, day: date, request: Request) -> dict:
    """Batch detector run over a cached day (doc §10) — the same engine the
    live loop runs, stepped across the whole session."""
    symbol = symbol.upper()
    conn = deps.get_db(request)
    cal = deps.get_calendar(request)
    fetcher = deps.get_fetcher(request)
    if fetcher is not None:
        try:
            fetcher.ensure_day(symbol, day)
        except NotTradingDay:
            raise HTTPException(status_code=404, detail=f"{day} is not a trading day")
        except (ProviderError, CalendarUnavailable) as e:
            logger.warning("scan lazy fetch failed %s %s: %s", symbol, day, e)
    try:
        signals = scan_day(conn, cal, symbol, day, request.app.state.rules)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"symbol": symbol, "day": day.isoformat(), "signals": [s.to_json() for s in signals]}


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
