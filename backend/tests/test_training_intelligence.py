"""Regression coverage for the post-v1 training intelligence features."""
from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import db
from app.journal import reviews
from app.marketdata.calendar import MarketCalendar
from app.models import CalendarDay, to_db_ts
from app.predictions import service as predictions
from app.risk import policy as risk_policy
from app.scenarios import service as scenarios
from app.sim.engine import SimEngine, Trade
from app.workouts import service as workouts

DAY = date(2026, 6, 16)
CAL_DAY = CalendarDay(DAY, "09:30", "16:00", "04:00", "20:00")


def _insert_calendar(conn) -> MarketCalendar:
    conn.execute(
        "INSERT INTO calendar VALUES (?, '09:30', '16:00', '04:00', '20:00')",
        (DAY.isoformat(),),
    )
    return MarketCalendar(conn, None)


def test_numbered_migration_is_recorded_and_idempotent(tmp_path):
    path = tmp_path / "migrations.db"
    conn = db.init_db(path)
    versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations")]
    assert versions == ["001_training_intelligence"]
    assert db.apply_migrations(conn) == []
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'trade_reviews'").fetchone()
    db.close_all()


def test_existing_database_runs_numbered_migration_before_schema_drift_pass(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE legacy_marker (id INTEGER PRIMARY KEY)")
    legacy.close()
    conn = db.init_db(path)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'workout_runs'").fetchone()
    assert conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = '001_training_intelligence'"
    ).fetchone()
    db.close_all()


def test_review_upsert_and_execution_metrics_are_derived(conn):
    _insert_calendar(conn)
    entry = datetime(2026, 6, 16, 14, 0, tzinfo=UTC)
    exit_ts = entry + timedelta(minutes=2)
    trade_id = conn.execute(
        "INSERT INTO trades (mode, day, symbol, direction, qty, entry_ts, entry_price, "
        "exit_ts, exit_price, stop_price, r_multiple) VALUES "
        "('practice', ?, 'SPY', 'long', 10, ?, 100, ?, 101, 99, 1)",
        (DAY.isoformat(), to_db_ts(entry), to_db_ts(exit_ts)),
    ).lastrowid
    for i, (high, low) in enumerate(((100.5, 99.5), (102.0, 99.8), (101.5, 100.5))):
        ts = to_db_ts(entry + timedelta(minutes=i))
        conn.execute(
            "INSERT INTO bars_1m VALUES ('SPY', ?, 100, ?, ?, 101, 1000, 'rth')",
            (ts, high, low),
        )
    review = reviews.upsert_review(
        conn,
        trade_id,
        {
            "thesis": "  reclaim  ", "notes": "patient", "confidence": 4,
            "emotion": "calm", "mistakes": ["Late Entry", "late entry"],
            "tags": ["A+", "a+"], "reviewed": True,
        },
    )
    assert review["thesis"] == "reclaim"
    assert review["mistakes"] == ["late entry"]
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    metrics = reviews.execution_metrics(conn, row)
    assert metrics["mfe_r"] == 2.0
    assert metrics["mae_r"] == -0.5
    assert metrics["duration_minutes"] == 2.0
    assert [marker["kind"] for marker in metrics["markers"]] == ["entry", "exit"]


def test_blind_scenario_payload_omits_answer_fields(conn):
    conn.execute(
        "INSERT INTO scenario_catalog VALUES "
        "('abc','SPY',?,'2026-06-16T14:00:00+00:00','orb_long','long',100,99,102,'Solid','[]',?)",
        (DAY.isoformat(), to_db_ts(datetime.now(UTC))),
    )
    blind = scenarios.list_catalog(conn, blind=True)["scenarios"][0]
    assert blind == {"id": "abc", "symbol": "SPY", "day": DAY.isoformat(), "blind": True}
    revealed = scenarios.list_catalog(conn, blind=False)["scenarios"][0]
    assert revealed["setup_type"] == "orb_long"
    assert revealed["direction"] == "long"


def test_daily_workout_is_deterministic_and_resumable(conn, monkeypatch):
    monkeypatch.setattr(
        workouts.drills,
        "unlocked_drillable",
        lambda _conn, _lessons, _rules: {
            "opening_range_breakout", "vwap_reclaim", "level_break"
        },
    )
    first = workouts.daily_plan(conn, [], {}, DAY)
    second = workouts.daily_plan(conn, [], {}, DAY)
    assert first["run"]["id"] == second["run"]["id"]
    assert sum(item["reps"] for item in first["items"]) == 9
    assert all(item["reason"] for item in first["items"])
    for item in first["items"]:
        result = workouts.complete_item(conn, first["run"]["id"], item["id"])
    assert result["run_complete"] is True


def test_prediction_locks_at_open_scores_after_close_and_labels_late(conn):
    calendar = _insert_calendar(conn)
    before = CAL_DAY.open_utc() - timedelta(minutes=30)
    after = CAL_DAY.close_utc() + timedelta(minutes=1)
    saved = predictions.save(
        conn, calendar, DAY, "SPY",
        {"direction": "bullish", "key_level": 101, "setup": "ORB", "invalidation": "below VWAP", "confidence": 4},
        before,
    )
    assert saved["score"]["status"] == "pending_session"
    for i, (open_, high, low, close) in enumerate(
        ((100, 101, 99, 100.5), (100.5, 103, 100, 102))
    ):
        conn.execute(
            "INSERT INTO bars_1m VALUES ('SPY', ?, ?, ?, ?, ?, 1000, 'rth')",
            (to_db_ts(CAL_DAY.open_utc() + timedelta(minutes=i)), open_, high, low, close),
        )
    scored = predictions.list_day(conn, calendar, DAY, after)["predictions"][0]
    assert scored["locked_at"] is not None
    assert scored["score"]["direction_correct"] is True
    assert scored["score"]["level_hit"] is True
    with pytest.raises(PermissionError):
        predictions.save(
            conn, calendar, DAY, "SPY",
            {"direction": "bearish", "confidence": 2}, after,
        )
    late = predictions.save(
        conn, calendar, DAY, "QQQ", {"direction": "neutral", "confidence": 2}, after,
    )
    assert late["is_late"] is True
    assert late["score"]["status"] == "late_not_scored"


def _risk_cfg(mode: str):
    return SimpleNamespace(
        risk_mode=mode,
        max_risk_per_trade_pct=1.0,
        max_daily_loss_r=3.0,
        max_trades_per_day=5,
        cooldown_minutes=5,
        max_open_risk_pct=2.0,
        require_protective_stop=True,
    )


def test_risk_policy_coaches_or_blocks_and_persists_events(conn):
    sim = SimEngine(10_000)
    now = datetime(2026, 6, 16, 14, 0, tzinfo=UTC)
    coached = risk_policy.evaluate_entry(sim, _risk_cfg("coach"), now, 200, 100, 99)
    assert coached["allowed"] is True
    assert {issue["rule_key"] for issue in coached["issues"]} == {"max_risk_per_trade"}
    enforced = risk_policy.evaluate_entry(sim, _risk_cfg("enforce"), now, 200, 100, 99)
    assert enforced["allowed"] is False
    assert enforced["issues"][0]["disposition"] == "blocked"
    risk_policy.record(
        conn, enforced, session_id="s1", mode="practice", day=DAY, now=now, action="entry"
    )
    status = risk_policy.status(conn, sim, _risk_cfg("enforce"), now, "s1")
    assert status["events"][0]["rule_key"] == "max_risk_per_trade"

    sim.trades.append(
        Trade(
            id=1, symbol="SPY", direction="long", qty=1, entry_ts=now - timedelta(minutes=2),
            entry_price=100, stop_price=99, exit_ts=now - timedelta(minutes=1),
            exit_price=97, r_multiple=-3.0,
        )
    )
    stopped = risk_policy.evaluate_entry(sim, _risk_cfg("enforce"), now, 10, 100, 99)
    keys = {issue["rule_key"] for issue in stopped["issues"]}
    assert {"max_daily_loss", "cooldown"} <= keys
