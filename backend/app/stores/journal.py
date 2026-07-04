"""Trade journal CRUD (doc §14): every closed round trip lands here with its
R-multiple. Grades/checklists join with the rules engine; equity and stats
are always DERIVED from these rows at read time, never stored."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.models import to_db_ts
from app.sim.engine import Trade


def insert_closed_trade(conn: sqlite3.Connection, mode: str, day: date, trade: Trade) -> int:
    assert trade.closed, "journal only records closed trades"
    cur = conn.execute(
        "INSERT INTO trades (mode, day, symbol, direction, qty, entry_ts, entry_price,"
        " exit_ts, exit_price, exit_reason, stop_price, r_multiple, setup_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            mode,
            day.isoformat(),
            trade.symbol,
            trade.direction,
            trade.qty,
            to_db_ts(trade.entry_ts),
            trade.entry_price,
            to_db_ts(trade.exit_ts) if trade.exit_ts else None,
            trade.exit_price,
            trade.exit_reason,
            trade.stop_price,
            trade.r_multiple,
            trade.setup_id,
        ),
    )
    return int(cur.lastrowid)


def list_trades(
    conn: sqlite3.Connection, mode: str | None = None, day: date | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM trades"
    where, args = [], []
    if mode:
        where.append("mode = ?")
        args.append(mode)
    if day:
        where.append("day = ?")
        args.append(day.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY entry_ts"
    return conn.execute(sql, args).fetchall()
