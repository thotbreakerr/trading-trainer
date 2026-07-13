"""Startup backups of the non-rebuildable user tables (doc §14).

The bar cache is rebuildable from Alpaca; progress/setups/orders/trades/
briefings are not. Backups are small single-file SQLite snapshots of just
those tables — a cold single file is safe to sync to OneDrive (unlike the
live WAL database), so the default destination inside the project folder is
deliberate. A backup is itself a valid app database: restore = copy it over
trainer.db (bars refetch lazily).
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import db
from app.db import SCHEMA_PATH
from app.models import utcnow

logger = logging.getLogger(__name__)

# Copy order satisfies the trades.setup_id -> setups.id foreign key.
USER_TABLES = (
    "progress", "setups", "orders", "trades", "briefings", "trade_reviews",
    "scenario_playlists", "scenario_playlist_items", "workout_runs", "workout_items",
    "briefing_predictions", "risk_events",
)
CACHE_TABLES = ("bars_1m", "bars_daily", "cached_days", "calendar", "scenario_catalog")
META_TABLES = ("schema_migrations",)

_NAME_RE = re.compile(r"^trainer-(\d{8})-(\d{6})\.db$")


def create_backup(db_path: Path, dest_dir: Path, *, now: datetime | None = None) -> Path:
    """Snapshot the user tables into dest_dir/trainer-YYYYMMDD-HHMMSS.db."""
    now = now or utcnow()
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / f"trainer-{now:%Y%m%d-%H%M%S}.db"
    tmp = final.with_name(final.name + ".tmp")
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("ATTACH DATABASE ? AS src", (str(db_path),))
        with conn:  # one transaction = consistent snapshot (WAL allows readers)
            for table in USER_TABLES:
                conn.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table}")
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    os.replace(tmp, final)  # OneDrive never sees a half-written file
    return final


def last_backup_time(dest_dir: Path) -> datetime | None:
    """Newest backup timestamp, parsed from filenames (garbage tolerated)."""
    if not dest_dir.is_dir():
        return None
    latest: datetime | None = None
    for p in dest_dir.iterdir():
        m = _NAME_RE.match(p.name)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        if latest is None or ts > latest:
            latest = ts
    return latest


def rotate(dest_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backups (ordered by filename)."""
    backups = sorted(
        (p for p in dest_dir.iterdir() if _NAME_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    removed: list[Path] = []
    for p in backups[keep:]:
        try:
            p.unlink()
            removed.append(p)
        except OSError as e:  # OneDrive may hold a lock; skip, retry next start
            logger.warning("could not remove old backup %s: %s", p, e)
    return removed


def _user_rows(conn: sqlite3.Connection) -> int:
    return sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in USER_TABLES)


def run_startup_backup(cfg, *, now: datetime | None = None) -> Path | None:
    """Gate + create + rotate. Never raises — backups must not stop the app.

    Gates: backup_keep <= 0 disables; empty user tables (fresh install) skip;
    a backup newer than backup_min_interval_hours skips.
    """
    try:
        if cfg.backup_keep <= 0:
            return None
        now = now or utcnow()
        last = last_backup_time(cfg.backup_dir)
        if last is not None and now - last < timedelta(hours=cfg.backup_min_interval_hours):
            return None
        if _user_rows(db.get_conn(cfg.db_path)) == 0:
            return None
        path = create_backup(cfg.db_path, cfg.backup_dir, now=now)
        rotate(cfg.backup_dir, cfg.backup_keep)
        logger.info("backup written: %s", path)
        return path
    except Exception as e:
        logger.warning("startup backup failed: %s", e)
        return None
