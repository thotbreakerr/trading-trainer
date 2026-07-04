"""The fake-live harness (doc §17.7): the REAL poller machinery driven across
a whole cached day by a fake wall clock — Market Day is testable at 2 AM."""
from __future__ import annotations

from datetime import date, timedelta

from app import db
from app.config import AppConfig
from app.marketday.poller import MarketDayPoller
from app.marketdata.calendar import MarketCalendar
from app.models import et_clock_to_utc
from app.stores import setups as setups_store
from tests.test_batch_golden import RULES, build_orb_day

ANCHOR = date(2026, 6, 16)


def make_cfg(tmp_path) -> AppConfig:
    return AppConfig(
        watchlist=["SPY"],
        starting_balance=30_000.0,
        intraday_leverage=4.0,
        default_risk_pct=1.0,
        backfill_days=5,
        rvol_baseline_days=3,
        # the harness drives 5-minute wall steps; staleness = 2.5x this
        poll_interval_seconds=300,
        db_path=tmp_path / "test.db",
        allow_untrained_trading=False,
    )


def make_poller(tmp_path, wall: dict) -> MarketDayPoller:
    return MarketDayPoller(
        cfg=make_cfg(tmp_path),
        rules_cfg=RULES | {"unlocks": {"opening_range_breakout": 8}},
        provider_fn=lambda: None,  # cache only
        lessons_fn=lambda: [],
        now_fn=lambda: wall["now"],
    )


def test_full_simulated_day(conn, tmp_path):
    build_orb_day(conn)
    cal_day = MarketCalendar(conn).day(ANCHOR)

    # before the session: idle
    wall = {"now": cal_day.session_open_utc() - timedelta(hours=1)}
    poller = make_poller(tmp_path, wall)
    assert poller.tick_once()["status"] == "idle"

    # drive the day in 5-minute wall steps (clock = wall - 15m)
    wall["now"] = cal_day.session_open_utc() + timedelta(minutes=15)
    end = cal_day.session_close_utc() + timedelta(minutes=16)
    summaries = []
    while wall["now"] < end:
        summaries.append(poller.tick_once())
        wall["now"] += timedelta(minutes=5)

    assert poller.session is not None and poller.session.day == ANCHOR
    assert all(s["status"] == "ok" for s in summaries)
    assert not poller.status_json()["stale"]

    rows = setups_store.list_setups(conn, ANCHOR, mode="marketday")
    types = {r["setup_type"] for r in rows}
    assert "orb_long" in types
    orb = next(r for r in rows if r["setup_type"] == "orb_long")
    assert orb["outcome"] == "target" and orb["outcome_r"] == 2.0
    # nothing was unlocked -> the coach stayed quiet but the ledger is full
    callouts = poller.callouts.visible(poller.session.clock.now())
    assert callouts and all(c["locked"] for c in callouts)


def test_staleness_reported_honestly(conn, tmp_path):
    build_orb_day(conn)
    cal_day = MarketCalendar(conn).day(ANCHOR)
    wall = {"now": cal_day.open_utc() + timedelta(hours=1)}
    poller = make_poller(tmp_path, wall)
    poller.tick_once()
    assert poller.status_json()["stale"] is False
    wall["now"] += timedelta(minutes=30)  # no ticks for half an hour
    status = poller.status_json()
    assert status["stale"] is True and status["stale_since"] is not None


def test_trading_gate_follows_module_nine(conn, tmp_path):
    build_orb_day(conn)
    poller = make_poller(tmp_path, {"now": et_clock_to_utc(ANCHOR, "12:00")})
    assert poller.trading_unlocked(conn) is False
    unlocked_cfg = make_cfg(tmp_path)
    unlocked_cfg.allow_untrained_trading = True  # the escape hatch (doc §12)
    poller_open = MarketDayPoller(
        cfg=unlocked_cfg, rules_cfg=RULES, provider_fn=lambda: None,
        lessons_fn=lambda: [], now_fn=lambda: et_clock_to_utc(ANCHOR, "12:00"),
    )
    assert poller_open.trading_unlocked(conn) is True