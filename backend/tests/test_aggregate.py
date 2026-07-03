"""Aggregation rules: bucket boundaries, sparse minutes, session isolation,
half-day clipping, DST sanity (doc §5, §8)."""
from __future__ import annotations

from datetime import date

import pytest

from app.marketdata.aggregate import aggregate_bars
from app.models import Bar, CalendarDay, et_clock_to_utc

DAY = date(2026, 6, 16)
HALF = date(2026, 11, 27)
DST_MON = date(2026, 3, 9)


def _cd(d: date, close: str = "16:00") -> CalendarDay:
    return CalendarDay(d, "09:30", close, "04:00", "20:00")


DAYS = {DAY: _cd(DAY), HALF: _cd(HALF, close="13:00"), DST_MON: _cd(DST_MON)}


def mk(hhmm: str, session: str, px: float = 100.0, vol: int = 100, d: date = DAY) -> Bar:
    return Bar("SPY", et_clock_to_utc(d, hhmm), px, px + 1, px - 1, px + 0.5, vol, session)


def test_5m_bucket_ohlcv_and_boundary():
    bars = [
        mk("09:30", "rth", 100.0),
        mk("09:31", "rth", 102.0),  # high 103
        mk("09:32", "rth", 96.0),   # low 95
        mk("09:34", "rth", 101.0),  # close 101.5
        mk("09:35", "rth", 200.0),  # next bucket
    ]
    out = aggregate_bars(bars, 5, DAYS)
    assert len(out) == 2
    b0 = out[0]
    assert b0.ts == et_clock_to_utc(DAY, "09:30")
    assert (b0.open, b0.high, b0.low, b0.close) == (100.0, 103.0, 95.0, 101.5)
    assert b0.volume == 400
    assert out[1].ts == et_clock_to_utc(DAY, "09:35") and out[1].open == 200.0


def test_sparse_minutes_share_a_bucket():
    out = aggregate_bars([mk("09:30", "rth"), mk("09:33", "rth", 101.0)], 5, DAYS)
    assert len(out) == 1
    assert out[0].volume == 200 and out[0].close == 101.5


def test_buckets_never_cross_session_boundaries():
    out = aggregate_bars([mk("09:29", "pre", 99.0), mk("09:30", "rth", 100.0)], 15, DAYS)
    assert [(b.ts, b.session) for b in out] == [
        (et_clock_to_utc(DAY, "09:15"), "pre"),   # anchored from 04:00
        (et_clock_to_utc(DAY, "09:30"), "rth"),   # fresh bucket at the bell
    ]


def test_hourly_anchors_per_segment():
    out = aggregate_bars(
        [
            mk("09:00", "pre", 98.0),   # pre hourly anchored 04:00 -> 09:00
            mk("09:30", "rth", 100.0),
            mk("10:29", "rth", 101.0),  # still the 09:30 RTH hourly
            mk("10:30", "rth", 102.0),  # next RTH hourly
        ],
        60,
        DAYS,
    )
    assert [b.ts for b in out] == [
        et_clock_to_utc(DAY, "09:00"),
        et_clock_to_utc(DAY, "09:30"),
        et_clock_to_utc(DAY, "10:30"),
    ]
    assert out[1].close == 101.5  # 10:29 closed the 09:30 hourly


def test_half_day_clips_from_calendar_row():
    out = aggregate_bars(
        [mk("12:59", "rth", d=HALF), mk("13:05", "post", d=HALF)], 60, DAYS
    )
    assert [(b.ts, b.session) for b in out] == [
        (et_clock_to_utc(HALF, "12:30"), "rth"),
        (et_clock_to_utc(HALF, "13:00"), "post"),  # post anchored at early close
    ]


def test_dst_day_buckets_at_correct_utc():
    out = aggregate_bars([mk("09:30", "rth", d=DST_MON)], 5, DAYS)
    assert out[0].ts.hour == 13 and out[0].ts.minute == 30  # EDT: 09:30 ET = 13:30Z


def test_1m_is_a_passthrough():
    bars = [mk("09:30", "rth"), mk("09:31", "rth")]
    assert aggregate_bars(bars, 1, DAYS) == bars


def test_missing_calendar_day_is_loud():
    with pytest.raises(ValueError, match="no calendar day"):
        aggregate_bars([mk("09:30", "rth", d=date(2026, 6, 17))], 5, DAYS)
