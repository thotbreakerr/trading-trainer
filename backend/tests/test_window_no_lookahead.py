"""The no-lookahead gate (doc §8): exact cutoffs, partial buckets, the hidden
replay day, and the poisoned-future regression — corrupt every bar beyond the
cutoff and require bit-identical outputs."""
from __future__ import annotations

from datetime import date, timedelta

from app.analysis.indicators import ema_series
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, FixedClock, ReplayClock
from app.models import Bar, CalendarDay, et_clock_to_utc
from tests.conftest import seed_days

ANCHOR = date(2026, 6, 17)


def _days() -> list[CalendarDay]:
    return [
        CalendarDay(date(2026, 6, 15), "09:30", "16:00", "04:00", "20:00"),
        CalendarDay(date(2026, 6, 16), "09:30", "16:00", "04:00", "20:00"),
        CalendarDay(ANCHOR, "09:30", "16:00", "04:00", "20:00"),
    ]


def make_window(conn, hhmm: str, lookback: int = 2) -> BarWindow:
    clock = FixedClock(et_clock_to_utc(ANCHOR, hhmm))
    return BarWindow(conn, MarketCalendar(conn), clock, ANCHOR, lookback_days=lookback)


def seeded(conn) -> None:
    seed_days(conn, "SPY", _days())


def test_cutoff_is_exact_bar_visibility(conn):
    seeded(conn)
    w = make_window(conn, "09:35")
    bars = w.bars_1m("SPY")
    anchor_rth = [b for b in bars if b.ts >= et_clock_to_utc(ANCHOR, "09:30")]
    # clock 09:35 -> cutoff 09:34 -> bars 09:30..09:34 visible, 09:35 not
    assert [b.ts for b in anchor_rth] == [
        et_clock_to_utc(ANCHOR, f"09:3{i}") for i in range(5)
    ]


def test_partial_bucket_contains_only_completed_minutes(conn):
    seeded(conn)
    w = make_window(conn, "09:37")  # cutoff 09:36
    five = w.bars("SPY", "5m")
    last = five[-1]
    assert last.ts == et_clock_to_utc(ANCHOR, "09:35")
    minutes = w.bars_1m("SPY", since=et_clock_to_utc(ANCHOR, "09:35"))
    assert [b.ts.minute for b in minutes] == [35, 36]
    assert last.volume == sum(b.volume for b in minutes)
    assert last.open == minutes[0].open and last.close == minutes[-1].close


def test_replay_day_starts_hidden_prior_days_full(conn):
    seeded(conn)
    w = BarWindow(
        conn,
        MarketCalendar(conn),
        ReplayClock(et_clock_to_utc(ANCHOR, "09:30")),
        ANCHOR,
        lookback_days=2,
    )
    bars = w.bars_1m("SPY")
    anchor_bars = [b for b in bars if b.ts >= et_clock_to_utc(ANCHOR, "04:00")]
    assert all(b.session == "pre" for b in anchor_bars)  # pre-market context only
    prior_post = [
        b for b in bars
        if et_clock_to_utc(date(2026, 6, 16), "16:00") <= b.ts < et_clock_to_utc(ANCHOR, "00:00")
    ]
    assert prior_post, "prior day must be fully visible including post-market"


def test_daily_context_is_strictly_before_anchor(conn):
    seeded(conn)
    w = make_window(conn, "12:00")
    days = [b.day for b in w.daily("SPY", 10)]
    assert days and all(d < ANCHOR for d in days)


def test_poisoned_future_changes_nothing(conn):
    seeded(conn)
    w = make_window(conn, "12:00")
    cutoff = w.cutoff()

    def snapshot():
        agg = w.bars("SPY", "5m")
        closes = [b.close for b in agg]
        return {
            "bars_5m": [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in agg],
            "last_1m": w.bars_1m("SPY")[-1].ts,
            "vwap": w.vwap("SPY"),
            "ema9": ema_series(closes, 9),
            "rvol": w.rvol("SPY", baseline_days=2),
            "sma200": w.sma200("SPY"),
        }

    before = snapshot()

    # Corrupt EVERYTHING beyond the cutoff with absurd values.
    future = store.get_bars_1m_raw(conn, "SPY", start=cutoff + timedelta(minutes=1))
    assert future, "test needs future bars to poison"
    store.upsert_bars_1m(
        conn,
        [
            Bar(b.symbol, b.ts, b.open * 100, b.high * 100, b.low * 100,
                b.close * 100, b.volume * 1000, b.session)
            for b in future
        ],
    )

    assert snapshot() == before