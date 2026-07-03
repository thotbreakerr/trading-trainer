"""Trading-session logic. Every open/close/half-day decision in the app reads
the cached exchange calendar — never a hardcoded time (doc §16.1). DST is safe
by construction: calendar rows carry ET clock strings, converted at use time.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.marketdata import store
from app.models import ET, SESSION_POST, SESSION_PRE, SESSION_RTH, CalendarDay
from app.providers.base import MarketDataProvider

STATE_PRE = "pre"
STATE_OPEN = "open"
STATE_POST = "post"
STATE_CLOSED = "closed"


class CalendarUnavailable(RuntimeError):
    """Calendar data missing for the requested range and no provider to fetch it."""


def tag_session(ts: datetime, cal: CalendarDay) -> str:
    """Session tag for a bar START time (a bar starting 15:59 ET is RTH;
    one starting at the close is post)."""
    if ts < cal.open_utc():
        return SESSION_PRE
    if ts < cal.close_utc():
        return SESSION_RTH
    return SESSION_POST


@dataclass(frozen=True)
class MarketState:
    state: str  # STATE_PRE | STATE_OPEN | STATE_POST | STATE_CLOSED
    display_day: date  # which trading day the UI should show
    today: CalendarDay | None  # today's calendar row, if today trades


class MarketCalendar:
    """Calendar cache + session helpers. Coverage invariant: rows exist for
    every trading day between the table's min and max day (fetches always
    cover the full union range, so bounds == coverage)."""

    def __init__(self, conn: sqlite3.Connection, provider: MarketDataProvider | None = None):
        self._conn = conn
        self._provider = provider

    # ------------------------------------------------------------- coverage

    def ensure_range(self, start: date, end: date) -> None:
        bounds = store.calendar_bounds(self._conn)
        if bounds and bounds[0] <= start and end <= bounds[1]:
            return
        if self._provider is None:
            raise CalendarUnavailable(
                f"calendar not cached for {start}..{end} and no API keys to fetch it"
            )
        lo = min(start, bounds[0]) if bounds else start
        hi = max(end, bounds[1]) if bounds else end
        store.upsert_calendar(self._conn, self._provider.get_calendar(lo, hi))
        new_bounds = store.calendar_bounds(self._conn)
        # A range that starts/ends on non-trading days can never be "covered"
        # by bounds (only trading days appear) — accept when the fetch brought
        # the edges as close as the exchange calendar allows.
        if new_bounds is None:
            raise CalendarUnavailable(f"provider returned no calendar for {lo}..{hi}")

    def _require(self, day_or_none: CalendarDay | None, what: str) -> CalendarDay:
        if day_or_none is None:
            raise CalendarUnavailable(f"no calendar coverage for {what}")
        return day_or_none

    # -------------------------------------------------------------- lookups

    def day(self, d: date) -> CalendarDay | None:
        return store.get_calendar_day(self._conn, d)

    def is_trading_day(self, d: date) -> bool:
        return self.day(d) is not None

    def latest_on_or_before(self, d: date) -> CalendarDay:
        days = store.calendar_days_before(self._conn, d, 1, inclusive=True)
        return self._require(days[0] if days else None, f"trading day on/before {d}")

    def prev_trading_day(self, d: date) -> CalendarDay:
        days = store.calendar_days_before(self._conn, d, 1, inclusive=False)
        return self._require(days[0] if days else None, f"trading day before {d}")

    def next_trading_day(self, d: date) -> CalendarDay:
        return self._require(
            store.calendar_day_after(self._conn, d), f"trading day after {d}"
        )

    def trading_days_back(self, end: date, n: int) -> list[CalendarDay]:
        """The n trading days ending at latest_on_or_before(end), ascending."""
        days = store.calendar_days_before(self._conn, end, n, inclusive=True)
        if len(days) < n:
            raise CalendarUnavailable(
                f"need {n} trading days back from {end}, calendar has {len(days)}"
            )
        return days

    def trading_days_between(self, start: date, end: date) -> list[CalendarDay]:
        return store.get_calendar_range(self._conn, start, end)

    # ---------------------------------------------------------- market state

    def market_state(self, now: datetime) -> MarketState:
        today_et = now.astimezone(ET).date()
        row = self.day(today_et)
        if row is None:  # weekend or holiday
            return MarketState(STATE_CLOSED, self.latest_on_or_before(today_et).day, None)
        if now < row.session_open_utc():  # small hours before pre-market
            return MarketState(STATE_CLOSED, self.prev_trading_day(today_et).day, row)
        if now < row.open_utc():
            return MarketState(STATE_PRE, row.day, row)
        if now < row.close_utc():
            return MarketState(STATE_OPEN, row.day, row)
        if now < row.session_close_utc():
            return MarketState(STATE_POST, row.day, row)
        return MarketState(STATE_CLOSED, row.day, row)

    # Convenience for callers that need a generous ensured window around today.
    def ensure_around(self, today: date, back_days: int = 420, ahead_days: int = 40) -> None:
        self.ensure_range(today - timedelta(days=back_days), today + timedelta(days=ahead_days))
