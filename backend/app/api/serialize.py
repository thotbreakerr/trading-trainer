"""Shared JSON shapes for bar/calendar payloads."""
from __future__ import annotations

from datetime import datetime

from app.models import Bar, CalendarDay


def bar_json(b: Bar) -> dict:
    return {
        "t": int(b.ts.timestamp()),
        "o": b.open,
        "h": b.high,
        "l": b.low,
        "c": b.close,
        "v": b.volume,
        "s": b.session,
    }


def day_meta(d: CalendarDay) -> dict:
    return {
        "day": d.day.isoformat(),
        "half_day": d.is_half_day,
        "session_open": int(d.session_open_utc().timestamp()),
        "open": int(d.open_utc().timestamp()),
        "close": int(d.close_utc().timestamp()),
        "session_close": int(d.session_close_utc().timestamp()),
    }


def point_json(series: list[tuple[datetime, float]]) -> list[dict]:
    return [{"t": int(ts.timestamp()), "v": value} for ts, value in series]
