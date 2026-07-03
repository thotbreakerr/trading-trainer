"""App factory: config, schema apply, key detection, routers.

Run with: python -m uvicorn app.main:app  (see run.ps1 — no --reload, a reload
restart would kill in-memory replay sessions and duplicate the poller task).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api import data, deps, system
from app.config import load_app_config, load_creds
from app.marketdata.calendar import MarketCalendar
from app.models import ET, utcnow

logger = logging.getLogger(__name__)


def _warm_calendar(app: FastAPI) -> None:
    conn = db.get_conn(app.state.cfg.db_path)
    MarketCalendar(conn, app.state.provider).ensure_around(
        utcnow().astimezone(ET).date()
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.state.provider is not None:
        try:
            await asyncio.to_thread(_warm_calendar, app)
        except Exception as e:  # offline start must still boot
            logger.warning("calendar warm-up failed: %s", e)
    yield


def create_app() -> FastAPI:
    cfg = load_app_config()
    db.init_db(cfg.db_path)
    app = FastAPI(title="Day Trading Trainer", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    deps.install_provider(app, load_creds())
    app.include_router(system.router, prefix="/api", tags=["system"])
    app.include_router(data.router, prefix="/api", tags=["data"])
    return app


app = create_app()
