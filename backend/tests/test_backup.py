"""User-data backups: filtered snapshot, gating, rotation (README Backups)."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app import backup, db

NOW = datetime(2026, 7, 6, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def user_db(tmp_path):
    """A tmp app DB with one row in every user table + one cached bar."""
    path = tmp_path / "trainer.db"
    conn = db.init_db(path)
    conn.execute("INSERT INTO progress (module, step, completed_at) VALUES (1, 0, '2026-07-06T12:00:00Z')")
    setup_id = conn.execute(
        "INSERT INTO setups (symbol, day, fired_ts, setup_type, direction, status, mode)"
        " VALUES ('SPY','2026-06-16','2026-06-16T13:45:00Z','orb_long','long','fired','practice')"
    ).lastrowid
    conn.execute(
        "INSERT INTO orders (mode, day, symbol, side, type, qty, status, placed_ts)"
        " VALUES ('practice','2026-06-16','SPY','buy','market',10,'filled','2026-06-16T13:46:00Z')"
    )
    trade_id = conn.execute(
        "INSERT INTO trades (mode, day, symbol, direction, qty, entry_ts, entry_price, setup_id)"
        " VALUES ('practice','2026-06-16','SPY','long',10,'2026-06-16T13:46:00Z',100.5,?)",
        (setup_id,),
    ).lastrowid
    conn.execute(
        "INSERT INTO briefings (day, created_at, snapshot) VALUES ('2026-06-16','2026-06-16T13:00:00Z','{}')"
    )
    conn.execute(
        "INSERT INTO trade_reviews (trade_id, updated_at) VALUES (?, '2026-06-16T20:00:00Z')",
        (trade_id,),
    )
    playlist_id = conn.execute(
        "INSERT INTO scenario_playlists (name, created_at) VALUES ('Openers','2026-06-16T20:00:00Z')"
    ).lastrowid
    conn.execute(
        "INSERT INTO scenario_playlist_items (playlist_id, scenario_id, position) VALUES (?, 's1', 0)",
        (playlist_id,),
    )
    workout_id = conn.execute(
        "INSERT INTO workout_runs (day, created_at) VALUES ('2026-06-16','2026-06-16T12:00:00Z')"
    ).lastrowid
    conn.execute(
        "INSERT INTO workout_items (run_id, position, setup, reps, weakness_score, reason) "
        "VALUES (?, 0, 'opening_range_breakout', 5, 1.0, 'Needs reps')",
        (workout_id,),
    )
    conn.execute(
        "INSERT INTO briefing_predictions "
        "(day, symbol, direction, confidence, created_at, updated_at) VALUES "
        "('2026-06-16','SPY','bullish',3,'2026-06-16T12:00:00Z','2026-06-16T12:00:00Z')"
    )
    conn.execute(
        "INSERT INTO risk_events (mode, day, ts, rule_key, action, disposition, detail) "
        "VALUES ('practice','2026-06-16','2026-06-16T14:00:00Z','max_trades','entry','warned','test')"
    )
    conn.execute("INSERT INTO bars_1m VALUES ('SPY','2026-06-16T13:45:00Z',1,2,0.5,1.5,1000,'rth')")
    yield SimpleNamespace(path=path, conn=conn)
    db.close_all()


def _cfg(user_db, dest, *, keep=14, interval=12.0):
    return SimpleNamespace(
        db_path=user_db.path, backup_dir=dest, backup_keep=keep, backup_min_interval_hours=interval
    )


def test_backup_contains_user_rows_and_no_bars(user_db, tmp_path):
    dest = tmp_path / "backups"
    path = backup.create_backup(user_db.path, dest, now=NOW)
    assert path.name == "trainer-20260706-180000.db"
    out = sqlite3.connect(path)
    try:
        for table in backup.USER_TABLES:
            assert out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1, table
        for table in backup.CACHE_TABLES:
            assert out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        # the trades -> setups FK linkage survived the copy
        assert out.execute("SELECT setup_id FROM trades").fetchone()[0] == 1
    finally:
        out.close()
    assert not list(dest.glob("*.tmp"))


def test_run_startup_backup_writes_then_respects_interval(user_db, tmp_path):
    dest = tmp_path / "backups"
    cfg = _cfg(user_db, dest)
    assert backup.run_startup_backup(cfg, now=NOW) is not None
    inside_window = datetime(2026, 7, 7, 5, 0, 0, tzinfo=UTC)  # 11h later
    assert backup.run_startup_backup(cfg, now=inside_window) is None
    outside_window = datetime(2026, 7, 7, 7, 30, 0, tzinfo=UTC)  # 13.5h later
    assert backup.run_startup_backup(cfg, now=outside_window) is not None
    assert len(list(dest.glob("trainer-*.db"))) == 2


def test_empty_user_tables_skip_backup(tmp_path):
    path = tmp_path / "trainer.db"
    db.init_db(path)
    cfg = SimpleNamespace(
        db_path=path, backup_dir=tmp_path / "b", backup_keep=14, backup_min_interval_hours=12.0
    )
    try:
        assert backup.run_startup_backup(cfg, now=NOW) is None
        assert not (tmp_path / "b").exists() or not list((tmp_path / "b").iterdir())
    finally:
        db.close_all()


def test_keep_zero_disables(user_db, tmp_path):
    assert backup.run_startup_backup(_cfg(user_db, tmp_path / "b", keep=0), now=NOW) is None


def test_rotation_keeps_newest(tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    for i in range(5):
        (dest / f"trainer-2026010{i + 1}-000000.db").write_bytes(b"x")
    removed = backup.rotate(dest, keep=2)
    assert len(removed) == 3
    left = sorted(p.name for p in dest.iterdir())
    assert left == ["trainer-20260104-000000.db", "trainer-20260105-000000.db"]


def test_garbage_filenames_are_ignored(tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    (dest / "notes.txt").write_text("hi", encoding="utf-8")
    (dest / "trainer-notadate.db").write_bytes(b"x")
    assert backup.last_backup_time(dest) is None
    (dest / "trainer-20260706-180000.db").write_bytes(b"x")
    assert backup.last_backup_time(dest) == NOW


def test_every_schema_table_is_classified(conn):
    """Drift guard: any future table must be filed as user data or cache."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    assert {r["name"] for r in rows} == (
        set(backup.USER_TABLES) | set(backup.CACHE_TABLES) | set(backup.META_TABLES)
    )
