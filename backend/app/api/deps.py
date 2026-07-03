"""FastAPI dependencies. Routers stay thin: validation + serialization only."""
from __future__ import annotations

import sqlite3

from fastapi import Request

from app import db
from app.config import AlpacaCreds, AppConfig
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.providers.alpaca import AlpacaProvider


def get_cfg(request: Request) -> AppConfig:
    return request.app.state.cfg


def get_db(request: Request) -> sqlite3.Connection:
    return db.get_conn(request.app.state.cfg.db_path)


def get_provider(request: Request) -> AlpacaProvider | None:
    return request.app.state.provider


def get_calendar(request: Request) -> MarketCalendar:
    return MarketCalendar(get_db(request), get_provider(request))


def get_fetcher(request: Request) -> Fetcher | None:
    provider = get_provider(request)
    if provider is None:
        return None
    cfg = get_cfg(request)
    return Fetcher(
        get_db(request),
        provider,
        get_calendar(request),
        rvol_baseline_days=cfg.rvol_baseline_days,
    )


def install_provider(app, creds: AlpacaCreds | None) -> None:
    app.state.provider = (
        AlpacaProvider(creds.key_id, creds.secret) if creds else None
    )
