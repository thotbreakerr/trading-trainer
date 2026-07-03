from datetime import UTC, date, datetime

from app.marketdata import store
from app.models import Bar, CalendarDay, DailyBar


def _bar(symbol: str, ts: datetime, px: float = 100.0) -> Bar:
    return Bar(
        symbol=symbol, ts=ts, open=px, high=px + 1, low=px - 1, close=px + 0.5,
        volume=1000, session="rth",
    )


T0 = datetime(2026, 6, 16, 13, 30, tzinfo=UTC)
T1 = datetime(2026, 6, 16, 13, 31, tzinfo=UTC)
T2 = datetime(2026, 6, 16, 13, 32, tzinfo=UTC)


def test_bars_1m_round_trip_and_idempotent_upsert(conn):
    bars = [_bar("SPY", T0), _bar("SPY", T1, 101.0), _bar("QQQ", T0, 400.0)]
    assert store.upsert_bars_1m(conn, bars) == 3
    store.upsert_bars_1m(conn, bars)  # idempotent: PK replace, no duplicates

    got = store.get_bars_1m_raw(conn, "SPY")
    assert [b.ts for b in got] == [T0, T1]
    assert got[0].symbol == "SPY" and got[0].close == 100.5
    assert got[0].ts.tzinfo is not None

    assert len(store.get_bars_1m_raw(conn, "QQQ")) == 1


def test_bars_1m_range_filters_inclusive(conn):
    store.upsert_bars_1m(conn, [_bar("SPY", t) for t in (T0, T1, T2)])
    assert [b.ts for b in store.get_bars_1m_raw(conn, "SPY", start=T1)] == [T1, T2]
    assert [b.ts for b in store.get_bars_1m_raw(conn, "SPY", end=T1)] == [T0, T1]
    assert [b.ts for b in store.get_bars_1m_raw(conn, "SPY", start=T1, end=T1)] == [T1]


def test_last_bar_ts(conn):
    store.upsert_bars_1m(conn, [_bar("SPY", t) for t in (T0, T2)])
    assert store.last_bar_ts(conn, "SPY", T0, T2) == T2
    assert store.last_bar_ts(conn, "SPY", T0, T1) == T0
    assert store.last_bar_ts(conn, "MSFT", T0, T2) is None


def test_daily_round_trip_and_bounds(conn):
    bars = [
        DailyBar("SPY", date(2026, 6, 15), 99, 102, 98, 101, 1_000_000),
        DailyBar("SPY", date(2026, 6, 16), 101, 103, 100, 102, 1_100_000),
    ]
    store.upsert_bars_daily(conn, bars)
    got = store.get_bars_daily_raw(conn, "SPY")
    assert [b.day for b in got] == [date(2026, 6, 15), date(2026, 6, 16)]
    assert store.daily_bounds(conn, "SPY") == (date(2026, 6, 15), date(2026, 6, 16))
    assert store.daily_bounds(conn, "QQQ") is None


def test_cached_days_bookkeeping(conn):
    d = date(2026, 6, 16)
    fetched1 = datetime(2026, 6, 16, 18, 0, tzinfo=UTC)
    fetched2 = datetime(2026, 6, 17, 1, 0, tzinfo=UTC)
    assert store.get_cached_day(conn, "SPY", d) is None
    store.mark_day_cached(conn, "SPY", d, fetched1)
    assert store.get_cached_day(conn, "SPY", d) == fetched1
    store.mark_day_cached(conn, "SPY", d, fetched2)  # re-mark overwrites
    assert store.get_cached_day(conn, "SPY", d) == fetched2
    assert store.list_cached_days(conn, "SPY") == [(d, fetched2)]


def test_calendar_round_trip_and_navigation(conn, cal_days):
    store.upsert_calendar(conn, cal_days)
    store.upsert_calendar(conn, cal_days)  # idempotent

    jun16 = store.get_calendar_day(conn, date(2026, 6, 16))
    assert jun16 is not None and jun16.open_et == "09:30"
    assert store.get_calendar_day(conn, date(2026, 6, 13)) is None  # Saturday

    rng = store.get_calendar_range(conn, date(2026, 6, 12), date(2026, 6, 16))
    assert [c.day.day for c in rng] == [12, 15, 16]

    before = store.calendar_days_before(conn, date(2026, 6, 15), 2)
    assert [c.day.day for c in before] == [11, 12]
    at_or_before = store.calendar_days_before(conn, date(2026, 6, 15), 2, inclusive=True)
    assert [c.day.day for c in at_or_before] == [12, 15]

    after = store.calendar_day_after(conn, date(2026, 11, 25))
    assert after is not None and after.day == date(2026, 11, 27)  # skips Thanksgiving

    lo, hi = store.calendar_bounds(conn)
    assert lo == date(2026, 3, 5) and hi == date(2026, 11, 30)


def test_delete_symbol_data_scoped_to_symbol(conn):
    store.upsert_bars_1m(conn, [_bar("SPY", T0), _bar("QQQ", T0, 400.0)])
    store.upsert_bars_daily(conn, [DailyBar("SPY", date(2026, 6, 16), 99, 102, 98, 101, 1)])
    store.mark_day_cached(conn, "SPY", date(2026, 6, 16), T0)
    store.mark_day_cached(conn, "QQQ", date(2026, 6, 16), T0)

    store.delete_symbol_data(conn, "SPY")

    assert store.get_bars_1m_raw(conn, "SPY") == []
    assert store.get_bars_daily_raw(conn, "SPY") == []
    assert store.list_cached_days(conn, "SPY") == []
    assert len(store.get_bars_1m_raw(conn, "QQQ")) == 1
    assert len(store.list_cached_days(conn, "QQQ")) == 1
