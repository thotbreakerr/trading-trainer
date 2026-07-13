"""Decision-focused trade reviews and bar-derived execution metrics."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, FixedClock
from app.models import from_db_ts, to_db_ts, utcnow

REVIEW_FIELDS = ("thesis", "notes", "confidence", "emotion", "mistakes", "tags", "reviewed")


def review_json(row: sqlite3.Row | dict) -> dict:
    data = dict(row)
    return {
        "thesis": data.get("review_thesis") or "",
        "notes": data.get("review_notes") or "",
        "confidence": data.get("review_confidence"),
        "emotion": data.get("review_emotion") or "",
        "mistakes": _json_list(data.get("review_mistakes")),
        "tags": _json_list(data.get("review_tags")),
        "reviewed": bool(data.get("review_reviewed") or 0),
        "updated_at": data.get("review_updated_at"),
    }


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def upsert_review(conn: sqlite3.Connection, trade_id: int, values: dict) -> dict:
    exists = conn.execute("SELECT 1 FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if exists is None:
        raise KeyError(trade_id)
    now = to_db_ts(utcnow())
    conn.execute(
        "INSERT INTO trade_reviews "
        "(trade_id, thesis, notes, confidence, emotion, mistakes, tags, reviewed, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(trade_id) DO UPDATE SET thesis=excluded.thesis, notes=excluded.notes, "
        "confidence=excluded.confidence, emotion=excluded.emotion, mistakes=excluded.mistakes, "
        "tags=excluded.tags, reviewed=excluded.reviewed, updated_at=excluded.updated_at",
        (
            trade_id,
            values.get("thesis", "").strip(),
            values.get("notes", "").strip(),
            values.get("confidence"),
            values.get("emotion", "").strip(),
            json.dumps(_clean_list(values.get("mistakes", []))),
            json.dumps(_clean_list(values.get("tags", []))),
            int(bool(values.get("reviewed"))),
            now,
        ),
    )
    row = conn.execute(
        "SELECT thesis AS review_thesis, notes AS review_notes, confidence AS review_confidence, "
        "emotion AS review_emotion, mistakes AS review_mistakes, tags AS review_tags, "
        "reviewed AS review_reviewed, updated_at AS review_updated_at "
        "FROM trade_reviews WHERE trade_id = ?",
        (trade_id,),
    ).fetchone()
    assert row is not None
    return review_json(row)


def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = str(value).strip().lower()
        if item and item not in out:
            out.append(item)
    return out[:20]


def execution_metrics(conn: sqlite3.Connection, trade: sqlite3.Row | dict) -> dict:
    """Derive excursion and efficiency from the immutable one-minute tape."""
    t = dict(trade)
    start = from_db_ts(t["entry_ts"])
    anchor_day = date.fromisoformat(t["day"])
    calendar = MarketCalendar(conn, None)
    cal_day = calendar.day(anchor_day)
    end = from_db_ts(t["exit_ts"]) if t.get("exit_ts") else cal_day.close_utc() if cal_day else start
    bars = []
    if cal_day is not None:
        window = BarWindow(
            conn, calendar, FixedClock(end + timedelta(minutes=1)), anchor_day, lookback_days=0
        )
        bars = [bar for bar in window.bars_1m(t["symbol"], since=start) if bar.ts <= end]
    risk = abs(t["entry_price"] - t["stop_price"]) if t.get("stop_price") is not None else 0.0
    favorable = adverse = 0.0
    for bar in bars:
        if t["direction"] == "long":
            favorable = max(favorable, bar.high - t["entry_price"])
            adverse = max(adverse, t["entry_price"] - bar.low)
        else:
            favorable = max(favorable, t["entry_price"] - bar.low)
            adverse = max(adverse, bar.high - t["entry_price"])
    mfe_r = round(favorable / risk, 3) if risk >= 0.01 else None
    mae_r = round(-adverse / risk, 3) if risk >= 0.01 else None
    realized = t.get("r_multiple")
    exit_efficiency = (
        round(realized / mfe_r, 3) if realized is not None and mfe_r is not None and mfe_r > 0 else None
    )
    entry_efficiency = (
        round(favorable / (favorable + adverse), 3) if favorable + adverse > 0 else None
    )
    duration = None
    if t.get("exit_ts"):
        duration = round((from_db_ts(t["exit_ts"]) - from_db_ts(t["entry_ts"])).total_seconds() / 60, 1)
    markers = [
        {"t": int(from_db_ts(t["entry_ts"]).timestamp()), "price": t["entry_price"], "kind": "entry", "label": "Entry"}
    ]
    if t.get("exit_ts") and t.get("exit_price") is not None:
        markers.append(
            {"t": int(from_db_ts(t["exit_ts"]).timestamp()), "price": t["exit_price"], "kind": "exit", "label": "Exit"}
        )
    return {
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "available_r": mfe_r,
        "entry_efficiency": entry_efficiency,
        "exit_efficiency": exit_efficiency,
        "duration_minutes": duration,
        "bars_measured": len(bars),
        "markers": markers,
    }
