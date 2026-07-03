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

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

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
    """Open (creating if needed) and apply the schema idempotently."""
    conn = get_conn(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


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
