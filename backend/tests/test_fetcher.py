"""Fetcher rules: lookback expansion, cache-hit no-refetch, incremental
today-fetch, session tagging, split detection (doc §5, §16.3)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher, NotTradingDay
from app.models import SESSION_POST, SESSION_PRE, SESSION_RTH, et_clock_to_utc
from tests.conftest import NOW_AFTER_CLOSE, NOW_MID_SESSION, FakeProvider, make_daily_series

DAY = date(2026, 6, 17)


def make_fetcher(conn, provider, now):
    calendar = MarketCalendar(conn, provider)
    return Fetcher(conn, provider, calendar, rvol_baseline_days=3, now_fn=lambda: now)


def test_ensure_day_fetches_lookback_window_in_one_run(conn, cal_days):
    provider = FakeProvider(cal_days)
    fetcher = make_fetcher(conn, provider, NOW_AFTER_CLOSE)

    report = fetcher.ensure_day("SPY", DAY)

    # window = requested day + 3 RVOL-baseline days, contiguous -> ONE request
    assert len(provider.calls_1m) == 1
    _, start, end = provider.calls_1m[0]
    assert start == et_clock_to_utc(date(2026, 6, 12), "04:00")
    assert end == et_clock_to_utc(DAY, "20:00")
    assert sorted(report.fetched_1m_days) == [
        date(2026, 6, 12), date(2026, 6, 15), date(2026, 6, 16), DAY,
    ]
    assert report.bars_added > 0
    assert report.daily_bars_added > 0
    assert [d for d, _ in store.list_cached_days(conn, "SPY")] == sorted(report.fetched_1m_days)


def test_complete_days_are_never_refetched(conn, cal_days):
    provider = FakeProvider(cal_days)
    fetcher = make_fetcher(conn, provider, NOW_AFTER_CLOSE)

    fetcher.ensure_day("SPY", DAY)
    calls_1m, calls_daily = len(provider.calls_1m), len(provider.calls_daily)

    report = fetcher.ensure_day("SPY", DAY)  # everything cached & complete

    assert len(provider.calls_1m) == calls_1m
    assert len(provider.calls_daily) == calls_daily
    assert report.bars_added == 0 and report.fetched_1m_days == []


def test_today_stays_incomplete_and_refetches_incrementally(conn, cal_days):
    provider = FakeProvider(cal_days, now_fn=lambda: NOW_MID_SESSION)
    fetcher = make_fetcher(conn, provider, NOW_MID_SESSION)
    fetcher.ensure_day("SPY", DAY)
    first_bar_count = len(store.get_bars_1m_raw(conn, "SPY"))

    # An hour later: only today should be refetched, starting after the last bar.
    later = NOW_MID_SESSION + timedelta(hours=1)
    provider.now_fn = lambda: later
    fetcher_later = make_fetcher(conn, provider, later)
    report = fetcher_later.ensure_day("SPY", DAY)

    assert report.fetched_1m_days == [DAY]
    _, start, end = provider.calls_1m[-1]
    assert start > et_clock_to_utc(DAY, "04:00")  # incremental, not from session open
    assert len(store.get_bars_1m_raw(conn, "SPY")) > first_bar_count


def test_bars_get_session_tags_from_calendar(conn, cal_days):
    provider = FakeProvider(cal_days)
    fetcher = make_fetcher(conn, provider, NOW_AFTER_CLOSE)
    fetcher.ensure_day("SPY", DAY)

    d = date(2026, 6, 16)
    day_bars = store.get_bars_1m_raw(
        conn, "SPY",
        start=et_clock_to_utc(d, "04:00"),
        end=et_clock_to_utc(d, "20:00"),
    )
    by_session = {s: [b for b in day_bars if b.session == s] for s in ("pre", "rth", "post")}
    assert len(by_session[SESSION_PRE]) == 3      # FakeProvider pre bars
    assert len(by_session[SESSION_RTH]) == 390    # full RTH minutes
    assert len(by_session[SESSION_POST]) == 2
    assert max(b.ts for b in by_session[SESSION_RTH]) == et_clock_to_utc(d, "15:59")


def test_non_trading_day_raises(conn, cal_days):
    provider = FakeProvider(cal_days)
    fetcher = make_fetcher(conn, provider, NOW_AFTER_CLOSE)
    with pytest.raises(NotTradingDay):
        fetcher.ensure_day("SPY", date(2026, 6, 13))  # Saturday


def test_split_detection_wipes_symbol_cache_and_refetches(conn, cal_days):
    # Simulate: cache was built pre-split at ~500; a 2:1 split happened since,
    # so a fresh fetch returns the same dates adjusted to ~250.
    june = [c for c in cal_days if c.day.month == 6]
    provider = FakeProvider(
        cal_days, daily_override={"SPY": make_daily_series("SPY", june, close=250.0)}
    )
    stale = make_daily_series("SPY", [c for c in june if c.day <= date(2026, 6, 10)], close=500.0)
    store.upsert_bars_daily(conn, stale)
    stale_mark = datetime(2026, 6, 11, 1, 0, tzinfo=UTC)
    store.mark_day_cached(conn, "SPY", date(2026, 6, 10), stale_mark)

    fetcher = make_fetcher(conn, provider, NOW_AFTER_CLOSE)
    report = fetcher.ensure_day("SPY", DAY)

    assert report.split_refetched
    assert len(provider.calls_daily) == 2  # detect -> wipe -> refetch
    closes = {b.close for b in store.get_bars_daily_raw(conn, "SPY")}
    assert closes == {250.0}  # no stale unadjusted rows survive
    assert store.get_cached_day(conn, "SPY", date(2026, 6, 10)) is None  # 1m cache invalidated
    # and the requested window was fetched fresh afterwards
    assert sorted(report.fetched_1m_days)[-1] == DAY


def test_backfill_covers_watchlist_and_reports_progress(conn, cal_days):
    provider = FakeProvider(cal_days)
    fetcher = make_fetcher(conn, provider, NOW_AFTER_CLOSE)
    seen: list[tuple[str, int, int]] = []

    reports = fetcher.backfill(["SPY", "QQQ"], days_back=3, on_progress=lambda s, i, t: seen.append((s, i, t)))

    assert seen == [("SPY", 0, 2), ("QQQ", 1, 2)]
    assert {r.symbol for r in reports} == {"SPY", "QQQ"}
    for sym in ("SPY", "QQQ"):
        days = [d for d, _ in store.list_cached_days(conn, sym)]
        assert days == [date(2026, 6, 12), date(2026, 6, 15), date(2026, 6, 16), DAY]
