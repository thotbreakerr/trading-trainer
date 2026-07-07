"""The Market Day poller (doc §11): delayed-live is the replay engine fed by
this loop. Every interval it fetches fresh (15-min-delayed) bars, reveals
them through the SAME session pipeline replay uses, runs the callout engine,
and persists what happened. Failures back off with a cap and are reported
honestly via /marketday/state (doc §16.6) — never silently stale.

Everything time- and I/O-shaped is injectable so tests (and the fake-live
CLI rig) can drive a full simulated day in seconds.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from app import db, sessions
from app.config import AppConfig
from app.detectors.engine import unlocked_setups
from app.marketdata.calendar import CalendarUnavailable, MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.marketdata.window import BarWindow, RvolBaseline
from app.marketday.callouts import CalloutEngine
from app.models import ET, utcnow
from app.sim.engine import SimEngine
from app.stores import journal, progress

logger = logging.getLogger(__name__)

MAX_BACKOFF_S = 300.0


@dataclass
class DelayedLiveClock:
    """Session clock = now − 15 min, labeled honestly in the UI (doc §11)."""

    now_fn: Callable[[], datetime] = utcnow
    delay: timedelta = timedelta(minutes=15)

    def now(self) -> datetime:
        return self.now_fn() - self.delay


@dataclass
class MarketDayPoller:
    cfg: AppConfig
    rules_cfg: dict
    provider_fn: Callable[[], object | None]  # app.state.provider, read live
    lessons_fn: Callable[[], list]  # app.state.lessons
    now_fn: Callable[[], datetime] = utcnow

    session: sessions.Session | None = None
    callouts: CalloutEngine | None = None
    baselines: dict[str, RvolBaseline | None] = field(default_factory=dict)
    last_success: datetime | None = None
    last_error: str | None = None
    backoff_s: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------ unlock state

    def _unlocked(self, conn) -> set[str]:
        modules = self.lessons_fn()
        done = progress.completed_steps(conn)
        completed = {
            m.module
            for m in modules
            if m.steps and done.get(m.module, set()) >= {s.index for s in m.steps}
        }
        return unlocked_setups(self.rules_cfg, completed)

    def trading_unlocked(self, conn) -> bool:
        """Doc §12: trading inside Market Day opens after Module 9 —
        or the config escape hatch."""
        if self.cfg.allow_untrained_trading:
            return True
        modules = self.lessons_fn()
        done = progress.completed_steps(conn)
        nine = next((m for m in modules if m.module == 9), None)
        return bool(
            nine and nine.steps and done.get(9, set()) >= {s.index for s in nine.steps}
        )

    # ---------------------------------------------------------------- the tick

    def tick_once(self) -> dict:
        """One poll cycle. Returns a status summary (also used by tests)."""
        with self.lock:
            return self._tick_locked()

    def _tick_locked(self) -> dict:
        conn = db.get_conn(self.cfg.db_path)
        provider = self.provider_fn()
        calendar = MarketCalendar(conn, provider)
        now = self.now_fn()
        try:
            calendar.ensure_around(now.astimezone(ET).date())
        except Exception as e:
            logger.debug("poller calendar refresh unavailable: %s", e)
        try:
            state = calendar.market_state(now)
        except CalendarUnavailable as e:
            self.last_error = str(e)
            return {"status": "no-calendar"}
        today = state.today
        if today is None or now < today.session_open_utc():
            return {"status": "idle", "market_state": state.state}

        if self.session is None or self.session.day != today.day:
            clock = DelayedLiveClock(now_fn=self.now_fn)
            self.session = sessions.create_session(
                calendar,
                list(self.cfg.watchlist),
                today.day,
                lookback_days=1,
                start="session_open",
                mode="marketday",
                sim=SimEngine(self.cfg.starting_balance, self.cfg.intraday_leverage, mode="marketday"),
                clock=clock,
            )
            self.callouts = CalloutEngine(
                rules_cfg=self.rules_cfg, unlocked=self._unlocked(conn)
            )
            self.baselines = {
                sym: RvolBaseline.load(conn, calendar, sym, today.day)
                for sym in self.session.symbols
            }
            logger.info("market-day session created for %s", today.day)

        assert self.callouts is not None
        # unlocks can change mid-day as lessons complete
        self.callouts.unlocked = self._unlocked(conn)

        fetch_errors: list[str] = []
        if provider is not None:
            fetcher = Fetcher(conn, provider, calendar,
                              rvol_baseline_days=self.cfg.rvol_baseline_days)
            for symbol in self.session.symbols:
                try:
                    fetcher.ensure_day(symbol, today.day)
                except Exception as e:
                    fetch_errors.append(f"{symbol}: {e}")
        if fetch_errors and len(fetch_errors) == len(self.session.symbols):
            # nothing refreshed: report stale, keep serving cache (doc §16.6)
            self.last_error = fetch_errors[0]
            raise RuntimeError(f"poll fetch failed: {fetch_errors[0][:200]}")

        window = BarWindow(conn, calendar, self.session.clock, today.day, lookback_days=1)
        result = sessions.tick_session(self.session, window)
        events = list(result.events)
        events += self.callouts.on_tick(
            conn, window, self.session.symbols, today.day, self.baselines
        )
        # journal write-through
        sim = self.session.sim
        if sim is not None:
            closed = [t for t in sim.trades if t.closed]
            for trade in closed[self.session.persisted_trades:]:
                journal.insert_closed_trade(conn, "marketday", self.session.day, trade)
            self.session.persisted_trades = len(closed)

        self.last_success = now
        self.last_error = None
        self.backoff_s = 0.0
        return {
            "status": "ok",
            "market_state": state.state,
            "revealed": {s: len(b) for s, b in result.new_bars.items()},
            "events": len(events),
        }

    # ------------------------------------------------------------- async loop

    async def run(self) -> None:
        interval = max(self.cfg.poll_interval_seconds, 10)
        while True:
            try:
                await asyncio.to_thread(self.tick_once)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = str(e)[:300]
                self.backoff_s = min(max(self.backoff_s * 2, interval), MAX_BACKOFF_S)
                logger.warning("poller tick failed (backoff %.0fs): %s", self.backoff_s, e)
            await asyncio.sleep(self.backoff_s or interval)

    # ---------------------------------------------------------------- status

    def status_json(self) -> dict:
        now = self.now_fn()
        stale_after = timedelta(seconds=self.cfg.poll_interval_seconds * 2.5)
        stale = (
            self.last_success is not None and (now - self.last_success) > stale_after
        )
        return {
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "stale": bool(stale or (self.last_success is None and self.last_error)),
            "stale_since": self.last_success.isoformat() if stale and self.last_success else None,
            "error": self.last_error,
        }
