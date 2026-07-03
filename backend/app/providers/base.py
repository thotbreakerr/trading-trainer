"""Market-data provider abstraction — the only seam to the outside world
(doc §3). Swapping providers later means implementing this Protocol."""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, Sequence

from app.models import CalendarDay, DailyBar, KeyValidation, RawBar


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class MarketDataProvider(Protocol):
    def get_bars_1m(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> dict[str, list[RawBar]]:
        """Completed 1-minute bars in [start, end), ts = bar start (UTC),
        ascending. Every requested symbol is a key, even when empty."""
        ...

    def get_bars_daily(
        self, symbols: Sequence[str], start: date, end: date
    ) -> dict[str, list[DailyBar]]:
        """Split-adjusted daily bars, inclusive ET-date range, ascending."""
        ...

    def get_calendar(self, start: date, end: date) -> list[CalendarDay]:
        """Exchange trading calendar; only trading days appear."""
        ...

    def validate_keys(self) -> KeyValidation:
        """Cheap calls proving both data and trading-host entitlements."""
        ...
