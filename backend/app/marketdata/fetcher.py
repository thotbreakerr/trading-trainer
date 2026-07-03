"""Lazy per-day fetch & cache (doc §5).

Rules encoded here:
- Loading a day always brings its lookback window: the RVOL baseline days of
  1m bars (which include the prior day for levels) plus ~200 trading days of
  daily history for SMA200/trend context.
- Cache forever: a day is COMPLETE once fetched safely after its extended
  close; complete days are never refetched. Today stays incomplete until
  after the close, so it refetches incrementally (doc §11 poller reuses this).
- Split safety (doc §16.3): newly fetched daily bars are compared against
  stored rows for the same dates — a >40% discrepancy means the adjustment
  basis changed (a split happened since we cached), so the symbol's whole
  cache is wiped and refetched.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Sequence

from app.marketdata import store
from app.marketdata.calendar import MarketCalendar, tag_session
from app.models import ET, Bar, CalendarDay, DailyBar, RawBar, et_date, utcnow
from app.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)

# A day counts as complete only if fetched after its extended close PLUS the
# provider's recent-data blackout (a 16:05 ET fetch can't see 19:49-20:00).
COMPLETENESS_LAG = timedelta(minutes=20)

DAILY_HISTORY_CAL_DAYS = 320  # ≥ 200 trading days for SMA200 context
SPLIT_MOVE_THRESHOLD = 0.40


class NotTradingDay(ValueError):
    pass


@dataclass
class EnsureReport:
    symbol: str
    requested: date
    fetched_1m_days: list[date] = field(default_factory=list)
    bars_added: int = 0
    daily_bars_added: int = 0
    split_refetched: bool = False
    warnings: list[str] = field(default_factory=list)


class Fetcher:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: MarketDataProvider,
        calendar: MarketCalendar,
        *,
        rvol_baseline_days: int = 20,
        now_fn: Callable[[], datetime] = utcnow,
    ):
        self._conn = conn
        self._provider = provider
        self._calendar = calendar
        self._rvol_days = rvol_baseline_days
        self._now = now_fn
        # Earliest daily-history start already requested per symbol, this
        # process. Providers return nothing before a symbol's listing date,
        # which is indistinguishable from "never fetched" in the tables —
        # without this memo such symbols would refetch dailies on every call.
        self._daily_requested: dict[str, date] = {}

    # ------------------------------------------------------------ public API

    def ensure_day(self, symbol: str, day: date) -> EnsureReport:
        """Make `day` (plus its lookback window) fully usable from cache."""
        self._calendar.ensure_range(
            day - timedelta(days=DAILY_HISTORY_CAL_DAYS + 30), day + timedelta(days=7)
        )
        if not self._calendar.is_trading_day(day):
            raise NotTradingDay(f"{day} is not a trading day (weekend or holiday)")
        report = EnsureReport(symbol=symbol, requested=day)
        self._ensure_daily(symbol, day, report)
        window = self._calendar.trading_days_back(day, self._rvol_days + 1)
        self._ensure_1m_days(symbol, window, report)
        return report

    def backfill(
        self,
        symbols: Sequence[str],
        days_back: int,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> list[EnsureReport]:
        """First-launch fetch: watchlist × last `days_back` trading days + today."""
        today_et = self._now().astimezone(ET).date()
        self._calendar.ensure_around(today_et)
        target = self._calendar.latest_on_or_before(today_et)
        window = self._calendar.trading_days_back(target.day, days_back + 1)
        reports = []
        for i, symbol in enumerate(symbols):
            if on_progress:
                on_progress(symbol, i, len(symbols))
            report = EnsureReport(symbol=symbol, requested=target.day)
            self._ensure_daily(symbol, target.day, report)
            self._ensure_1m_days(symbol, window, report)
            reports.append(report)
        return reports

    def is_day_complete(self, symbol: str, cal_day: CalendarDay) -> bool:
        fetched_at = store.get_cached_day(self._conn, symbol, cal_day.day)
        if fetched_at is None:
            return False
        return fetched_at > cal_day.session_close_utc() + COMPLETENESS_LAG

    # ------------------------------------------------------------- 1m window

    def _ensure_1m_days(
        self, symbol: str, window: list[CalendarDay], report: EnsureReport
    ) -> None:
        need = [cd for cd in window if not self.is_day_complete(symbol, cd)]
        if not need:
            return
        index = {cd.day: i for i, cd in enumerate(window)}
        runs: list[list[CalendarDay]] = []
        for cd in need:  # group days adjacent in the trading-day sequence
            if runs and index[cd.day] == index[runs[-1][-1].day] + 1:
                runs[-1].append(cd)
            else:
                runs.append([cd])
        for run in runs:
            start = run[0].session_open_utc()
            end = run[-1].session_close_utc()
            if len(run) == 1 and store.get_cached_day(self._conn, symbol, run[0].day):
                # Partially cached day (today, usually): fetch only the tail.
                last = store.last_bar_ts(self._conn, symbol, start, end)
                if last is not None:
                    start = last + timedelta(minutes=1)
            raw = self._provider.get_bars_1m([symbol], start, end)[symbol]
            bars = self._tag_bars(symbol, raw, run, report)
            report.bars_added += store.upsert_bars_1m(self._conn, bars)
            fetched_at = self._now()
            for cd in run:
                store.mark_day_cached(self._conn, symbol, cd.day, fetched_at)
                report.fetched_1m_days.append(cd.day)

    def _tag_bars(
        self,
        symbol: str,
        raw: list[RawBar],
        run: list[CalendarDay],
        report: EnsureReport,
    ) -> list[Bar]:
        by_day = {cd.day: cd for cd in run}
        bars: list[Bar] = []
        skipped = 0
        for rb in raw:
            cal = by_day.get(et_date(rb.ts))
            if cal is None:  # bar on a day we didn't ask about — provider quirk
                skipped += 1
                continue
            bars.append(
                Bar(
                    symbol=symbol,
                    ts=rb.ts,
                    open=rb.open,
                    high=rb.high,
                    low=rb.low,
                    close=rb.close,
                    volume=rb.volume,
                    session=tag_session(rb.ts, cal),
                )
            )
        if skipped:
            report.warnings.append(f"{symbol}: skipped {skipped} bars outside requested days")
        return bars

    # ---------------------------------------------------------- daily history

    def _ensure_daily(self, symbol: str, upto: date, report: EnsureReport) -> None:
        target_start = upto - timedelta(days=DAILY_HISTORY_CAL_DAYS)
        prev = self._calendar.prev_trading_day(upto)
        bounds = store.daily_bounds(self._conn, symbol)
        if bounds is not None and bounds[1] >= prev.day:
            requested = self._daily_requested.get(symbol)
            if requested is not None and requested <= target_start:
                return  # already asked the provider for at least this window
            # Old-edge check against the CALENDAR: coverage is fine when no
            # trading day existed between target_start and our earliest row.
            first_needed = store.calendar_day_after(
                self._conn, target_start - timedelta(days=1)
            )
            if first_needed is None or first_needed.day >= bounds[0]:
                self._daily_requested[symbol] = min(target_start, requested or target_start)
                return
        fetched = self._provider.get_bars_daily([symbol], target_start, upto)[symbol]
        if self._split_detected(symbol, fetched):
            report.split_refetched = True
            report.warnings.append(
                f"{symbol}: split-adjustment change detected — wiped and refetching cache"
            )
            logger.warning("split detected for %s; wiping cached data", symbol)
            store.delete_symbol_data(self._conn, symbol)
            fetched = self._provider.get_bars_daily([symbol], target_start, upto)[symbol]
        report.daily_bars_added += store.upsert_bars_daily(self._conn, fetched)
        prior = self._daily_requested.get(symbol)
        self._daily_requested[symbol] = min(target_start, prior or target_start)
        self._warn_seams(symbol, report)

    def _split_detected(self, symbol: str, fetched: list[DailyBar]) -> bool:
        """Compare newly fetched dailies against stored rows for the SAME dates:
        a >40% close discrepancy means the split-adjustment basis changed."""
        if not fetched:
            return False
        stored = {
            b.day: b
            for b in store.get_bars_daily_raw(
                self._conn, symbol, fetched[0].day, fetched[-1].day
            )
        }
        for new in fetched:
            old = stored.get(new.day)
            if old is None or old.close <= 0:
                continue
            if abs(new.close / old.close - 1.0) > SPLIT_MOVE_THRESHOLD:
                return True
        return False

    def _warn_seams(self, symbol: str, report: EnsureReport) -> None:
        """Flag genuine >40% overnight moves left in the daily table (a real
        gap, or a split older than our history) — informational only."""
        dailies = store.get_bars_daily_raw(self._conn, symbol)
        for prev_bar, cur in zip(dailies, dailies[1:]):
            if prev_bar.close <= 0:
                continue
            if abs(cur.open / prev_bar.close - 1.0) > SPLIT_MOVE_THRESHOLD:
                report.warnings.append(
                    f"{symbol}: >40% overnight move {prev_bar.day} -> {cur.day}"
                    " (verify: real gap vs unadjusted split)"
                )
