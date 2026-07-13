"""Prediction locking and outcome scoring against the completed session."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, eod_clock
from app.models import et_date, to_db_ts, utcnow


def _ohlc(
    conn: sqlite3.Connection, calendar: MarketCalendar, symbol: str, day: date
) -> dict | None:
    cal_day = calendar.day(day)
    if cal_day is None:
        return None
    window = BarWindow(conn, calendar, eod_clock(cal_day), day, lookback_days=0)
    bars = [
        bar for bar in window.bars_1m(symbol)
        if bar.session == "rth" and et_date(bar.ts) == day
    ]
    if not bars:
        return None
    return {
        "open": bars[0].open,
        "high": max(bar.high for bar in bars),
        "low": min(bar.low for bar in bars),
        "close": bars[-1].close,
    }


def lock_day(conn: sqlite3.Connection, calendar: MarketCalendar, day: date, now: datetime) -> bool:
    cal_day = calendar.day(day)
    if cal_day is None or now < cal_day.open_utc():
        return False
    conn.execute(
        "UPDATE briefing_predictions SET locked_at = COALESCE(locked_at, ?) WHERE day = ?",
        (to_db_ts(now), day.isoformat()),
    )
    return True


def score_prediction(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    row: sqlite3.Row | dict,
    *,
    session_complete: bool = True,
) -> dict:
    p = dict(row)
    if p["is_late"]:
        return {"status": "late_not_scored", "total": None}
    if not session_complete:
        return {"status": "pending_session", "total": None}
    actual = _ohlc(conn, calendar, p["symbol"], date.fromisoformat(p["day"]))
    if actual is None or not actual["open"]:
        return {"status": "pending_data", "total": None}
    move = (actual["close"] / actual["open"] - 1) * 100
    actual_direction = "neutral"
    if move > 0.15:
        actual_direction = "bullish"
    elif move < -0.15:
        actual_direction = "bearish"
    correct = p["direction"] == actual_direction
    probability = 0.5 + p["confidence"] * 0.08
    brier = round((probability - int(correct)) ** 2, 3)
    level_hit = p["key_level"] is not None and actual["low"] <= p["key_level"] <= actual["high"]
    plan_points = 10 * int(bool(p["setup"].strip())) + 10 * int(bool(p["invalidation"].strip()))
    total = round(50 * int(correct) + 20 * int(level_hit) + plan_points + 10 * (1 - brier), 1)
    return {
        "status": "scored", "total": total, "direction_correct": correct,
        "actual_direction": actual_direction, "day_move_pct": round(move, 2),
        "level_hit": level_hit, "brier": brier, "plan_points": plan_points,
        "actual": actual,
    }


def list_day(
    conn: sqlite3.Connection, calendar: MarketCalendar, day: date, now: datetime | None = None
) -> dict:
    now = now or utcnow()
    locked = lock_day(conn, calendar, day, now)
    rows = conn.execute(
        "SELECT * FROM briefing_predictions WHERE day = ? ORDER BY symbol", (day.isoformat(),)
    ).fetchall()
    cal_day = calendar.day(day)
    session_complete = cal_day is not None and now >= cal_day.close_utc()
    return {
        "day": day.isoformat(), "locked": locked,
        "predictions": [
            {
                **dict(row),
                "is_late": bool(row["is_late"]),
                "score": score_prediction(conn, calendar, row, session_complete=session_complete),
            }
            for row in rows
        ],
    }


def save(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    day: date,
    symbol: str,
    values: dict,
    now: datetime | None = None,
) -> dict:
    now = now or utcnow()
    cal_day = calendar.day(day)
    if cal_day is None:
        raise ValueError("prediction day is not a trading day")
    existing = conn.execute(
        "SELECT * FROM briefing_predictions WHERE day = ? AND symbol = ?",
        (day.isoformat(), symbol),
    ).fetchone()
    after_open = now >= cal_day.open_utc()
    if existing is not None and (existing["locked_at"] or after_open):
        if not existing["locked_at"]:
            lock_day(conn, calendar, day, now)
        raise PermissionError("prediction locked at the market open")
    now_s = to_db_ts(now)
    is_late = int(after_open)
    locked_at = now_s if after_open else None
    conn.execute(
        "INSERT INTO briefing_predictions "
        "(day, symbol, direction, key_level, setup, invalidation, confidence, created_at, updated_at, locked_at, is_late) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(day, symbol) DO UPDATE SET direction=excluded.direction, key_level=excluded.key_level, "
        "setup=excluded.setup, invalidation=excluded.invalidation, confidence=excluded.confidence, "
        "updated_at=excluded.updated_at, locked_at=excluded.locked_at, is_late=excluded.is_late",
        (
            day.isoformat(), symbol, values["direction"], values.get("key_level"),
            values.get("setup", "").strip(), values.get("invalidation", "").strip(),
            values["confidence"], now_s, now_s, locked_at, is_late,
        ),
    )
    row = conn.execute(
        "SELECT * FROM briefing_predictions WHERE day = ? AND symbol = ?",
        (day.isoformat(), symbol),
    ).fetchone()
    assert row is not None
    return {
        **dict(row),
        "is_late": bool(row["is_late"]),
        "score": score_prediction(
            conn, calendar, row, session_complete=now >= cal_day.close_utc()
        ),
    }
