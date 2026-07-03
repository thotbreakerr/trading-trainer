"""Shared fixtures: tmp database, hand-authored calendar, FakeProvider.

The calendar fixture deliberately includes the awkward cases: a DST-shift
week (US spring-forward: Sun 2026-03-08), a Thanksgiving half day
(2026-11-27, 13:00 ET close), and a plain June window used by fetcher tests.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Callable, Sequence

import pytest

from app import db
from app.models import CalendarDay, DailyBar, KeyValidation, RawBar, et_clock_to_utc

# Fixed "now" for fetcher tests: Wed 2026-06-17 14:00 ET, mid-session.
NOW_MID_SESSION = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)
# Safely after Jun 17's extended close (20:00 ET = 00:00 UTC Jun 18) + lag.
NOW_AFTER_CLOSE = datetime(2026, 6, 18, 1, 0, tzinfo=UTC)


def _cd(d: date, close: str = "16:00") -> CalendarDay:
    return CalendarDay(
        day=d,
        open_et="09:30",
        close_et=close,
        session_open_et="04:00",
        session_close_et="20:00",
    )


def fixture_calendar() -> list[CalendarDay]:
    days: list[CalendarDay] = []
    # DST week: spring-forward is Sunday 2026-03-08
    for d in (date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)):
        days.append(_cd(d))
    # June window (weekdays Jun 1 .. Jun 17)
    d = date(2026, 6, 1)
    while d <= date(2026, 6, 17):
        if d.weekday() < 5:
            days.append(_cd(d))
        d += timedelta(days=1)
    # Thanksgiving week: Thu 11-26 closed, Fri 11-27 half day
    days.append(_cd(date(2026, 11, 25)))
    days.append(_cd(date(2026, 11, 27), close="13:00"))
    days.append(_cd(date(2026, 11, 30)))
    return days


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(tmp_path / "test.db")
    yield connection
    db.close_all()  # release Windows file locks so tmp_path can be removed


@pytest.fixture
def cal_days() -> list[CalendarDay]:
    return fixture_calendar()


class FakeProvider:
    """Deterministic in-memory MarketDataProvider.

    1m bars per trading day: a few pre-market bars, full RTH minutes, a few
    post bars — prices derived from (day, minute index) so tests can assert
    exact values. Honors the real provider's recent-data clamp when now_fn
    is supplied (completed bars only, up to now-16min).
    """

    PRE_ET = ("07:30", "08:30", "09:00")
    POST_ET = ("16:00", "17:00")

    def __init__(
        self,
        cal_days: Sequence[CalendarDay],
        *,
        now_fn: Callable[[], datetime] | None = None,
        daily_override: dict[str, list[DailyBar]] | None = None,
        base_price: float = 500.0,
    ):
        self.cal_days = sorted(cal_days, key=lambda c: c.day)
        self.now_fn = now_fn
        self.daily_override = daily_override or {}
        self.base_price = base_price
        self.calls_1m: list[tuple[list[str], datetime, datetime]] = []
        self.calls_daily: list[tuple[list[str], date, date]] = []
        self.calendar_calls = 0

    # ------------------------------------------------------------- 1m bars

    def _day_bar_times(self, cal: CalendarDay) -> list[datetime]:
        times: list[datetime] = []
        for hhmm in self.PRE_ET:
            times.append(et_clock_to_utc(cal.day, hhmm))
        t = cal.open_utc()
        close = cal.close_utc()
        while t < close:
            times.append(t)
            t += timedelta(minutes=1)
        for hhmm in self.POST_ET:
            ts = et_clock_to_utc(cal.day, hhmm)
            if ts >= close:  # half days: 16:00/17:00 are both post already
                times.append(ts)
        return times

    def get_bars_1m(self, symbols, start, end):
        self.calls_1m.append((list(symbols), start, end))
        if self.now_fn is not None:
            end = min(end, self.now_fn() - timedelta(minutes=16))
        out: dict[str, list[RawBar]] = {s: [] for s in symbols}
        if start >= end:
            return out
        for sym in symbols:
            bars: list[RawBar] = []
            for cal in self.cal_days:
                if cal.session_close_utc() < start or cal.session_open_utc() > end:
                    continue
                for i, ts in enumerate(self._day_bar_times(cal)):
                    if not (start <= ts < end):
                        continue
                    px = self.base_price + cal.day.day + i * 0.01
                    bars.append(
                        RawBar(
                            ts=ts,
                            open=px,
                            high=px + 0.05,
                            low=px - 0.05,
                            close=px + 0.02,
                            volume=10_000 + i,
                        )
                    )
            out[sym] = bars
        return out

    # ----------------------------------------------------------- daily bars

    def get_bars_daily(self, symbols, start, end):
        self.calls_daily.append((list(symbols), start, end))
        out: dict[str, list[DailyBar]] = {}
        for sym in symbols:
            if sym in self.daily_override:
                out[sym] = [b for b in self.daily_override[sym] if start <= b.day <= end]
                continue
            bars = []
            for cal in self.cal_days:
                if not (start <= cal.day <= end):
                    continue
                px = self.base_price + cal.day.day
                bars.append(
                    DailyBar(
                        symbol=sym,
                        day=cal.day,
                        open=px - 1,
                        high=px + 2,
                        low=px - 2,
                        close=px,
                        volume=1_000_000,
                    )
                )
            out[sym] = bars
        return out

    # ------------------------------------------------------------- calendar

    def get_calendar(self, start, end):
        self.calendar_calls += 1
        return [c for c in self.cal_days if start <= c.day <= end]

    def validate_keys(self) -> KeyValidation:
        return KeyValidation(data_ok=True, trading_ok=True)


def seed_days(conn, symbol: str, days: Sequence[CalendarDay], base: float = 500.0) -> None:
    """Insert calendar + tagged 1m bars + dailies for whole COMPLETE days —
    the starting state for window/session tests."""
    from datetime import timedelta

    from app.marketdata import store
    from app.marketdata.calendar import tag_session
    from app.models import Bar

    provider = FakeProvider(days, base_price=base)
    store.upsert_calendar(conn, days)
    for cd in days:
        raw = provider.get_bars_1m([symbol], cd.session_open_utc(), cd.session_close_utc())[symbol]
        bars = [
            Bar(symbol, rb.ts, rb.open, rb.high, rb.low, rb.close, rb.volume, tag_session(rb.ts, cd))
            for rb in raw
        ]
        store.upsert_bars_1m(conn, bars)
        store.mark_day_cached(conn, symbol, cd.day, cd.session_close_utc() + timedelta(hours=1))
    dailies = provider.get_bars_daily([symbol], days[0].day, days[-1].day)[symbol]
    store.upsert_bars_daily(conn, dailies)


def make_daily_series(
    symbol: str, days: Sequence[CalendarDay], close: float
) -> list[DailyBar]:
    """Flat daily series at a fixed close — handy for split-detection tests."""
    return [
        DailyBar(
            symbol=symbol,
            day=c.day,
            open=close - 1,
            high=close + 2,
            low=close - 2,
            close=close,
            volume=1_000_000,
        )
        for c in days
    ]
