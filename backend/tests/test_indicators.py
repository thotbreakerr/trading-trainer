from datetime import date

import pytest

from app.analysis.indicators import (
    cumulative_volume_at,
    ema_series,
    et_minutes,
    rvol_at,
    sma,
    vwap_series,
)
from app.models import Bar, et_clock_to_utc

DAY = date(2026, 6, 16)
DAY2 = date(2026, 6, 17)


def mk(hhmm: str, session: str, px: float, vol: int, d: date = DAY) -> Bar:
    ts = et_clock_to_utc(d, hhmm)
    return Bar("SPY", ts, px, px + 1, px - 1, px, vol, session)


def test_vwap_typical_price_weighted_and_rth_only():
    bars = [
        mk("09:00", "pre", 999.0, 10_000),  # ignored: not RTH
        mk("09:30", "rth", 100.0, 100),     # typical (101+99+100)/3 = 100
        mk("09:31", "rth", 104.0, 300),     # typical 104
    ]
    series = vwap_series(bars)
    assert len(series) == 2
    assert series[0][1] == pytest.approx(100.0)
    assert series[1][1] == pytest.approx((100 * 100 + 104 * 300) / 400)


def test_vwap_resets_each_trading_day():
    bars = [
        mk("09:30", "rth", 100.0, 100),
        mk("09:30", "rth", 200.0, 100, d=DAY2),
    ]
    series = vwap_series(bars)
    assert series[1][1] == pytest.approx(200.0)  # day 2 starts fresh


def test_ema_seeded_with_first_value():
    assert ema_series([1.0, 2.0, 3.0], 3) == [1.0, 1.5, 2.25]  # k = 0.5
    assert ema_series([], 9) == []


def test_sma_needs_full_period():
    assert sma([1.0, 2.0, 3.0], 4) is None
    assert sma([1.0, 2.0, 3.0, 4.0], 2) == pytest.approx(3.5)  # last two


def test_cumulative_volume_is_clock_based_not_index_based():
    sparse = [mk("09:30", "rth", 100, 200), mk("09:33", "rth", 100, 200)]
    assert cumulative_volume_at(sparse, et_minutes(sparse[0].ts)) == 200
    assert cumulative_volume_at(sparse, et_minutes(sparse[1].ts)) == 400


def test_rvol_cumulative_time_of_day():
    baseline_day = [mk("09:3%d" % i, "rth", 100, 100) for i in range(5)]  # 09:30..09:34
    today = [mk("09:30", "rth", 100, 200), mk("09:33", "rth", 100, 200)]  # sparse
    at = et_minutes(et_clock_to_utc(DAY, "09:33"))
    # baseline cum at 09:33 = 400; today cum = 400
    assert rvol_at(today, [baseline_day], at) == pytest.approx(1.0)
    # two baseline days -> mean of 400 and 800 = 600
    double = [mk("09:3%d" % i, "rth", 100, 200) for i in range(5)]
    assert rvol_at(today, [baseline_day, double], at) == pytest.approx(400 / 600)


def test_rvol_without_baseline_is_none():
    assert rvol_at([mk("09:30", "rth", 100, 100)], [], 600) is None
    assert rvol_at([mk("09:30", "rth", 100, 100)], [[]], 600) is None
