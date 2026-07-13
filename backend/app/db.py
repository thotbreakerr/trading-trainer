"""SQLite access: thread-local connections, WAL, idempotent schema apply.

Connections are autocommit; multi-statement writes use the transaction()
context manager. FastAPI runs sync endpoints in a threadpool, so each thread
gets its own connection lazily.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.models import to_db_ts, utcnow

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")

_local = threading.local()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn(db_path: Path) -> sqlite3.Connection:
    conns: dict[str, sqlite3.Connection] | None = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    key = str(db_path)
    conn = conns.get(key)
    if conn is None:
        conn = conns[key] = _connect(db_path)
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create from the full schema, or migrate an existing database first."""
    conn = get_conn(db_path)
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone()
    if existing:
        # Existing installs evolve through numbered transactions. Applying the
        # complete schema afterward remains an idempotent drift safety net.
        apply_migrations(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    else:
        # Fresh installs are already at the complete schema; mark every
        # migration represented by that schema without replaying it.
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        now = to_db_ts(utcnow())
        conn.executemany(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            [(path.stem, now) for path in sorted(MIGRATIONS_DIR.glob("*.sql"))],
        )
    return conn


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply numbered SQL migrations once, each in its own transaction."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL) WITHOUT ROWID"
    )
    applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    installed: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        applied_at = to_db_ts(utcnow()).replace("'", "''")
        safe_version = version.replace("'", "''")
        try:
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + script
                + f"\nINSERT INTO schema_migrations VALUES ('{safe_version}', '{applied_at}');\n"
                + "COMMIT;"
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        installed.append(version)
    return installed


def close_all() -> None:
    """Close this thread's connections (tests: releases Windows file locks)."""
    conns: dict[str, sqlite3.Connection] = getattr(_local, "conns", None) or {}
    for conn in conns.values():
        conn.close()
    conns.clear()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
