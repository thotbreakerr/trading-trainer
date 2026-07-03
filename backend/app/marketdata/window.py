"""Clock-gated bar access — THE single no-lookahead enforcement point (doc §8).

Every consumer of bars (chart API, detectors, sim context, grader, briefing)
reads through a BarWindow bound to a Clock. Raw store reads anywhere except
fetcher.py and this module are forbidden — tests/test_import_hygiene.py
enforces that mechanically.

Visibility rule: 1m bars are stamped at bar START; a bar exists once complete,
i.e. iff bar.ts + 60s <= clock.now(). Aggregated views clamp 1m FIRST, then
bucket — the trailing partial bucket contains only completed minutes, exactly
what a live chart shows.

This module ships with the chart shell (fixed end-of-day clocks for browsing
completed days); ReplayClock and the delayed-live clock arrive with the
replay engine and Market Day.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from app.marketdata import store
from app.marketdata.aggregate import TF_MINUTES, aggregate_bars
from app.marketdata.calendar import MarketCalendar
from app.models import Bar, CalendarDay, DailyBar

BAR_SECONDS = 60


class Clock(Protocol):
    def now(self) -> datetime:  # tz-aware UTC
        ...


@dataclass
class FixedClock:
    """A frozen clock. eod_clock() gives one that reveals a whole day."""

    at: datetime

    def now(self) -> datetime:
        return self.at


def eod_clock(cal_day: CalendarDay) -> FixedClock:
    # At exactly session close, the final bar (close - 1min) is complete.
    return FixedClock(cal_day.session_close_utc())


class BarWindow:
    """Clock-clipped reads over one anchor trading day plus context lookback.

    Prior days in the window render fully once the clock passes them; the
    anchor (replay) day reveals bar by bar as the clock advances.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        calendar: MarketCalendar,
        clock: Clock,
        anchor_day: date,
        lookback_days: int = 3,
    ):
        self._conn = conn
        self._calendar = calendar
        self.clock = clock
        self.days: list[CalendarDay] = calendar.trading_days_back(
            anchor_day, lookback_days + 1
        )
        self.anchor: CalendarDay = self.days[-1]
        if self.anchor.day != anchor_day:
            raise ValueError(f"{anchor_day} is not a trading day")
        self._day_map = {d.day: d for d in self.days}
        self._start = self.days[0].session_open_utc()

    # ------------------------------------------------------------ bar access

    def cutoff(self) -> datetime:
        """Latest visible bar START: bar.ts + 60s <= now."""
        return self.clock.now() - timedelta(seconds=BAR_SECONDS)

    def bars_1m(self, symbol: str, since: datetime | None = None) -> list[Bar]:
        start = since if since is not None and since > self._start else self._start
        end = self.cutoff()
        if end < start:
            return []
        return store.get_bars_1m_raw(self._conn, symbol, start=start, end=end)

    def bars(self, symbol: str, tf: str) -> list[Bar]:
        """Aggregated view: clamp to the clock FIRST, then bucket."""
        return aggregate_bars(self.bars_1m(symbol), TF_MINUTES[tf], self._day_map)

    def daily(self, symbol: str, n: int) -> list[DailyBar]:
        """Up to n daily bars STRICTLY before the anchor day (context only —
        the anchor day's daily bar would leak its close)."""
        rows = store.get_bars_daily_raw(
            self._conn, symbol, end=self.anchor.day - timedelta(days=1)
        )
        return rows[-n:]
