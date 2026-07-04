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
from app.api import data, deps, lessons_api, marketday_api, sessions_api, system
from app.config import PROJECT_ROOT, load_app_config, load_creds, load_rules_config
from app.lessons.loader import load_lessons, validate_demo_days
from app.marketday.poller import MarketDayPoller
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.models import ET, utcnow

logger = logging.getLogger(__name__)

LESSONS_DIR = PROJECT_ROOT / "lessons"


def _warm_calendar(app: FastAPI) -> None:
    conn = db.get_conn(app.state.cfg.db_path)
    MarketCalendar(conn, app.state.provider).ensure_around(
        utcnow().astimezone(ET).date()
    )


def _validate_lessons(app: FastAPI) -> None:
    conn = db.get_conn(app.state.cfg.db_path)
    calendar = MarketCalendar(conn, app.state.provider)
    fetcher = Fetcher(
        conn,
        app.state.provider,
        calendar,
        rvol_baseline_days=app.state.cfg.rvol_baseline_days,
    )
    validate_demo_days(app.state.lessons, fetcher, calendar)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.state.provider is not None:
        try:
            await asyncio.to_thread(_warm_calendar, app)
        except Exception as e:  # offline start must still boot
            logger.warning("calendar warm-up failed: %s", e)
        try:
            await asyncio.to_thread(_validate_lessons, app)
        except Exception as e:
            logger.warning("lesson validation failed: %s", e)
    poller = MarketDayPoller(
        cfg=app.state.cfg,
        rules_cfg=app.state.rules,
        provider_fn=lambda: app.state.provider,
        lessons_fn=lambda: app.state.lessons,
    )
    app.state.poller = poller
    task = asyncio.create_task(poller.run())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    cfg = load_app_config()
    db.init_db(cfg.db_path)
    app = FastAPI(title="Day Trading Trainer", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.rules = load_rules_config()
    app.state.lessons = load_lessons(LESSONS_DIR)
    deps.install_provider(app, load_creds())
    app.include_router(system.router, prefix="/api", tags=["system"])
    app.include_router(data.router, prefix="/api", tags=["data"])
    app.include_router(sessions_api.router, prefix="/api", tags=["sessions"])
    app.include_router(lessons_api.router, prefix="/api", tags=["lessons"])
    app.include_router(marketday_api.router, prefix="/api", tags=["marketday"])
    return app


app = create_app()
