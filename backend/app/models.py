"""Core domain types and time conventions. Pure data — no I/O, no DB.

Conventions (doc §14): timestamps are stored as ISO-8601 UTC text; session
logic happens in ET; display happens in CT. Every datetime in the codebase is
timezone-aware — naive datetimes are a bug.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")

SESSION_PRE = "pre"
SESSION_RTH = "rth"
SESSION_POST = "post"


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_db_ts(ts: datetime) -> str:
    """Aware datetime -> canonical UTC ISO string (sorts lexicographically)."""
    if ts.tzinfo is None:
        raise ValueError(f"naive datetime {ts!r}; all timestamps must be tz-aware")
    return ts.astimezone(UTC).replace(microsecond=0).isoformat()


def from_db_ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def et_clock_to_utc(day: date, hhmm: str) -> datetime:
    """'09:30' on an ET calendar date -> aware UTC datetime (DST-safe)."""
    h, m = hhmm.split(":")
    return datetime.combine(day, time(int(h), int(m)), tzinfo=ET).astimezone(UTC)


def et_date(ts: datetime) -> date:
    """The ET trading date a UTC timestamp belongs to."""
    return ts.astimezone(ET).date()


@dataclass(frozen=True, slots=True)
class RawBar:
    """Provider bar before session tagging. ts = bar START, aware UTC."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class Bar:
    """Stored 1-minute bar — the atomic data unit (doc §5). ts = bar START."""

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    session: str  # SESSION_PRE | SESSION_RTH | SESSION_POST


@dataclass(frozen=True, slots=True)
class DailyBar:
    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """One trading day. Clock times kept as ET strings exactly as the exchange
    publishes them — converting at use time makes DST handling automatic."""

    day: date
    open_et: str  # "09:30"
    close_et: str  # "16:00", or e.g. "13:00" on half days
    session_open_et: str  # "04:00" — extended-hours start
    session_close_et: str  # "20:00" — extended-hours end

    @property
    def is_half_day(self) -> bool:
        return self.close_et != "16:00"

    def open_utc(self) -> datetime:
        return et_clock_to_utc(self.day, self.open_et)

    def close_utc(self) -> datetime:
        return et_clock_to_utc(self.day, self.close_et)

    def session_open_utc(self) -> datetime:
        return et_clock_to_utc(self.day, self.session_open_et)

    def session_close_utc(self) -> datetime:
        return et_clock_to_utc(self.day, self.session_close_et)


@dataclass(frozen=True, slots=True)
class KeyValidation:
    """Result of proving both Alpaca entitlements (data + trading hosts)."""

    data_ok: bool
    trading_ok: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.data_ok and self.trading_ok
