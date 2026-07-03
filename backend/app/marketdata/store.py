"""SQLite CRUD for market data and the calendar cache.

NO-LOOKAHEAD CONTRACT (doc §8): the raw bar reads in this module are consumed
ONLY by marketdata.fetcher and marketdata.window. Every other consumer (chart
API, detectors, sim, grader, briefing) must read bars through a clock-bound
BarWindow. tests/test_import_hygiene.py enforces this mechanically.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Iterable

from app.db import transaction
from app.models import Bar, CalendarDay, DailyBar, from_db_ts, to_db_ts

# ------------------------------------------------------------------ 1m bars


def upsert_bars_1m(conn: sqlite3.Connection, bars: Iterable[Bar]) -> int:
    rows = [
        (b.symbol, to_db_ts(b.ts), b.open, b.high, b.low, b.close, b.volume, b.session)
        for b in bars
    ]
    if not rows:
        return 0
    with transaction(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO bars_1m (symbol, ts, open, high, low, close, volume, session)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def get_bars_1m_raw(
    conn: sqlite3.Connection,
    symbol: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Bar]:
    """Raw read, [start, end] inclusive. fetcher/window ONLY — see module note."""
    sql = "SELECT * FROM bars_1m WHERE symbol = ?"
    args: list = [symbol]
    if start is not None:
        sql += " AND ts >= ?"
        args.append(to_db_ts(start))
    if end is not None:
        sql += " AND ts <= ?"
        args.append(to_db_ts(end))
    sql += " ORDER BY ts"
    return [
        Bar(
            symbol=r["symbol"],
            ts=from_db_ts(r["ts"]),
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            session=r["session"],
        )
        for r in conn.execute(sql, args)
    ]


def last_bar_ts(
    conn: sqlite3.Connection, symbol: str, start: datetime, end: datetime
) -> datetime | None:
    """Latest stored bar start within [start, end] (incremental today-fetch)."""
    row = conn.execute(
        "SELECT MAX(ts) AS m FROM bars_1m WHERE symbol = ? AND ts >= ? AND ts <= ?",
        (symbol, to_db_ts(start), to_db_ts(end)),
    ).fetchone()
    return from_db_ts(row["m"]) if row and row["m"] else None


def delete_symbol_data(conn: sqlite3.Connection, symbol: str) -> None:
    """Wipe one symbol's market-data cache (split refetch, doc §16.3)."""
    with transaction(conn):
        conn.execute("DELETE FROM bars_1m WHERE symbol = ?", (symbol,))
        conn.execute("DELETE FROM bars_daily WHERE symbol = ?", (symbol,))
        conn.execute("DELETE FROM cached_days WHERE symbol = ?", (symbol,))


# ---------------------------------------------------------------- daily bars


def upsert_bars_daily(conn: sqlite3.Connection, bars: Iterable[DailyBar]) -> int:
    rows = [
        (b.symbol, b.day.isoformat(), b.open, b.high, b.low, b.close, b.volume)
        for b in bars
    ]
    if not rows:
        return 0
    with transaction(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO bars_daily (symbol, day, open, high, low, close, volume)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def get_bars_daily_raw(
    conn: sqlite3.Connection,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> list[DailyBar]:
    """Raw read, inclusive range. fetcher/window ONLY — see module note."""
    sql = "SELECT * FROM bars_daily WHERE symbol = ?"
    args: list = [symbol]
    if start is not None:
        sql += " AND day >= ?"
        args.append(start.isoformat())
    if end is not None:
        sql += " AND day <= ?"
        args.append(end.isoformat())
    sql += " ORDER BY day"
    return [
        DailyBar(
            symbol=r["symbol"],
            day=date.fromisoformat(r["day"]),
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
        )
        for r in conn.execute(sql, args)
    ]


def daily_bounds(conn: sqlite3.Connection, symbol: str) -> tuple[date, date] | None:
    row = conn.execute(
        "SELECT MIN(day) AS lo, MAX(day) AS hi FROM bars_daily WHERE symbol = ?",
        (symbol,),
    ).fetchone()
    if not row or row["lo"] is None:
        return None
    return date.fromisoformat(row["lo"]), date.fromisoformat(row["hi"])


# --------------------------------------------------------------- cached_days


def mark_day_cached(
    conn: sqlite3.Connection, symbol: str, day: date, fetched_at: datetime
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO cached_days (symbol, day, fetched_at) VALUES (?, ?, ?)",
        (symbol, day.isoformat(), to_db_ts(fetched_at)),
    )


def get_cached_day(
    conn: sqlite3.Connection, symbol: str, day: date
) -> datetime | None:
    row = conn.execute(
        "SELECT fetched_at FROM cached_days WHERE symbol = ? AND day = ?",
        (symbol, day.isoformat()),
    ).fetchone()
    return from_db_ts(row["fetched_at"]) if row else None


def list_cached_days(
    conn: sqlite3.Connection, symbol: str
) -> list[tuple[date, datetime]]:
    return [
        (date.fromisoformat(r["day"]), from_db_ts(r["fetched_at"]))
        for r in conn.execute(
            "SELECT day, fetched_at FROM cached_days WHERE symbol = ? ORDER BY day",
            (symbol,),
        )
    ]


def count_bars_1m_for_day(
    conn: sqlite3.Connection, symbol: str, start: datetime, end: datetime
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM bars_1m WHERE symbol = ? AND ts >= ? AND ts <= ?",
        (symbol, to_db_ts(start), to_db_ts(end)),
    ).fetchone()
    return int(row["n"])


# ------------------------------------------------------------------ calendar


def upsert_calendar(conn: sqlite3.Connection, days: Iterable[CalendarDay]) -> int:
    rows = [
        (d.day.isoformat(), d.open_et, d.close_et, d.session_open_et, d.session_close_et)
        for d in days
    ]
    if not rows:
        return 0
    with transaction(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO calendar"
            " (day, open_et, close_et, session_open_et, session_close_et)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def _row_to_calendar(r: sqlite3.Row) -> CalendarDay:
    return CalendarDay(
        day=date.fromisoformat(r["day"]),
        open_et=r["open_et"],
        close_et=r["close_et"],
        session_open_et=r["session_open_et"],
        session_close_et=r["session_close_et"],
    )


def get_calendar_day(conn: sqlite3.Connection, day: date) -> CalendarDay | None:
    row = conn.execute("SELECT * FROM calendar WHERE day = ?", (day.isoformat(),)).fetchone()
    return _row_to_calendar(row) if row else None


def get_calendar_range(
    conn: sqlite3.Connection, start: date, end: date
) -> list[CalendarDay]:
    return [
        _row_to_calendar(r)
        for r in conn.execute(
            "SELECT * FROM calendar WHERE day >= ? AND day <= ? ORDER BY day",
            (start.isoformat(), end.isoformat()),
        )
    ]


def calendar_days_before(
    conn: sqlite3.Connection, day: date, n: int, inclusive: bool = False
) -> list[CalendarDay]:
    """Up to n trading days at or before `day`, ascending order."""
    op = "<=" if inclusive else "<"
    rows = conn.execute(
        f"SELECT * FROM calendar WHERE day {op} ? ORDER BY day DESC LIMIT ?",
        (day.isoformat(), n),
    ).fetchall()
    return [_row_to_calendar(r) for r in reversed(rows)]


def calendar_day_after(conn: sqlite3.Connection, day: date) -> CalendarDay | None:
    row = conn.execute(
        "SELECT * FROM calendar WHERE day > ? ORDER BY day LIMIT 1", (day.isoformat(),)
    ).fetchone()
    return _row_to_calendar(row) if row else None


def calendar_bounds(conn: sqlite3.Connection) -> tuple[date, date] | None:
    row = conn.execute("SELECT MIN(day) AS lo, MAX(day) AS hi FROM calendar").fetchone()
    if not row or row["lo"] is None:
        return None
    return date.fromisoformat(row["lo"]), date.fromisoformat(row["hi"])
