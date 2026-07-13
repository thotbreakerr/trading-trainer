"""Build and query a no-provider scenario index from complete cached days."""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import date, datetime, timedelta

from app.detectors.engine import build_snapshot, scan_day
from app.detectors.types import Signal
from app.drill.service import DRILLABLE, concept_of
from app.grading.grader import grade_signal
from app.marketdata import store
from app.marketdata.calendar import CalendarUnavailable, MarketCalendar
from app.marketdata.window import BarWindow, FixedClock, eod_clock
from app.marketday.hindsight import track_outcome
from app.models import ET, et_date, from_db_ts, to_db_ts, utcnow

MAX_INDEX_PAIRS = 80


def catalog_item(row: sqlite3.Row | dict, blind: bool) -> dict:
    row = dict(row)
    item = {"id": row["id"], "symbol": row["symbol"], "day": row["day"], "blind": blind}
    if not blind:
        item.update(
            setup_type=row["setup_type"], direction=row["direction"], grade=row["grade"],
            fired_et=from_db_ts(row["fired_ts"]).astimezone(ET).strftime("%H:%M"),
        )
    return item


def _scenario_id(symbol: str, day: date, signal: Signal) -> str:
    raw = f"{symbol}:{day}:{to_db_ts(signal.ts)}:{signal.setup_type}:{signal.direction}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_catalog(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    rules_cfg: dict,
    watchlist: list[str],
    *,
    refresh: bool = False,
    max_pairs: int = MAX_INDEX_PAIRS,
) -> dict:
    """Index recent complete cache pairs. Existing identities are upserted."""
    if not refresh and conn.execute("SELECT 1 FROM scenario_catalog LIMIT 1").fetchone():
        count = conn.execute("SELECT COUNT(*) FROM scenario_catalog").fetchone()[0]
        return {"indexed": 0, "total": count}
    candidates: list[tuple[str, date]] = []
    for symbol in watchlist:
        for day, fetched_at in store.list_cached_days(conn, symbol):
            cal_day = calendar.day(day)
            if cal_day is not None and fetched_at > cal_day.session_close_utc():
                candidates.append((symbol, day))
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    indexed = 0
    now = to_db_ts(utcnow())
    for symbol, day in candidates[:max_pairs]:
        try:
            signals = scan_day(conn, calendar, symbol, day, rules_cfg, unlocked=set(DRILLABLE))
        except (ValueError, CalendarUnavailable):
            continue
        for signal in signals:
            if concept_of(signal.setup_type) is None:
                continue
            if signal.entry is None or signal.stop is None or signal.target is None:
                continue
            grade = None
            checklist = None
            try:
                window = BarWindow(
                    conn,
                    calendar,
                    FixedClock(signal.ts + timedelta(minutes=1)),
                    day,
                    lookback_days=1,
                )
                result = grade_signal(
                    signal,
                    build_snapshot(window, symbol),
                    rules_cfg.get("grading", {}),
                )
                if result:
                    grade = result.tier
                    checklist = json.dumps(result.to_json()["checklist"])
            except (ValueError, CalendarUnavailable):
                pass
            conn.execute(
                "INSERT OR REPLACE INTO scenario_catalog "
                "(id, symbol, day, fired_ts, setup_type, direction, entry, stop, target, grade, checklist, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _scenario_id(symbol, day, signal), symbol, day.isoformat(),
                    to_db_ts(signal.ts), signal.setup_type, signal.direction,
                    signal.entry, signal.stop, signal.target, grade, checklist, now,
                ),
            )
            indexed += 1
    total = conn.execute("SELECT COUNT(*) FROM scenario_catalog").fetchone()[0]
    return {"indexed": indexed, "total": total}


def list_catalog(
    conn: sqlite3.Connection,
    *,
    setup: str | None = None,
    direction: str | None = None,
    symbol: str | None = None,
    grade: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    blind: bool = True,
) -> dict:
    sql = "SELECT * FROM scenario_catalog"
    where: list[str] = []
    args: list = []
    if setup:
        prefixes = DRILLABLE.get(setup)
        if prefixes:
            where.append("(" + " OR ".join("setup_type LIKE ?" for _ in prefixes) + ")")
            args.extend(f"{prefix}%" for prefix in prefixes)
        else:
            where.append("setup_type LIKE ?")
            args.append(f"%{setup}%")
    if direction in ("long", "short"):
        where.append("direction = ?")
        args.append(direction)
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.upper())
    if grade:
        where.append("grade = ?")
        args.append(grade)
    if date_from:
        where.append("day >= ?")
        args.append(date_from.isoformat())
    if date_to:
        where.append("day <= ?")
        args.append(date_to.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY day DESC, symbol, fired_ts LIMIT ?"
    args.append(limit)
    rows = [dict(row) for row in conn.execute(sql, args)]
    items = [catalog_item(row, blind) for row in rows]
    return {
        "scenarios": items,
        "total": conn.execute("SELECT COUNT(*) FROM scenario_catalog").fetchone()[0],
        "setups": [{"key": key, "label": key.replace("_", " ").title()} for key in DRILLABLE],
    }


def resolution(conn: sqlite3.Connection, calendar: MarketCalendar, scenario_id: str) -> dict:
    row = conn.execute("SELECT * FROM scenario_catalog WHERE id = ?", (scenario_id,)).fetchone()
    if row is None:
        raise KeyError(scenario_id)
    day = date.fromisoformat(row["day"])
    cal_day = calendar.day(day)
    if cal_day is None:
        raise ValueError("scenario trading day is no longer in the calendar cache")
    window = BarWindow(conn, calendar, eod_clock(cal_day), day, lookback_days=1)
    fired = from_db_ts(row["fired_ts"])
    bars = [b for b in window.bars_1m(row["symbol"]) if et_date(b.ts) == day and b.ts >= fired]
    outcome = track_outcome(
        bars, row["direction"], row["entry"], row["stop"], row["target"]
    )
    return {
        "id": row["id"], "symbol": row["symbol"], "day": row["day"],
        "setup_type": row["setup_type"], "direction": row["direction"],
        "fired_ts": row["fired_ts"], "fired_et": fired.astimezone(ET).strftime("%H:%M"),
        "entry": row["entry"], "stop": row["stop"], "target": row["target"],
        "grade": row["grade"], "checklist": json.loads(row["checklist"] or "[]"),
        "outcome": outcome.outcome, "outcome_r": outcome.r_multiple, "exit_price": outcome.exit_price,
    }


def start_at(conn: sqlite3.Connection, scenario_id: str, open_ts: datetime) -> tuple[sqlite3.Row, datetime]:
    row = conn.execute("SELECT * FROM scenario_catalog WHERE id = ?", (scenario_id,)).fetchone()
    if row is None:
        raise KeyError(scenario_id)
    fired = from_db_ts(row["fired_ts"])
    rng = random.Random(scenario_id)
    return row, max(open_ts, fired - timedelta(minutes=rng.randint(10, 25)))
