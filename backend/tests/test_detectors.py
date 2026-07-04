"""Per-detector boundary tests on synthetic bars — thresholds exactly at the
cutoff (doc §10). Synthetic data in tests doesn't violate 'actual data only';
that's a product rule."""
from __future__ import annotations

from datetime import date

from app.analysis.levels import Levels
from app.detectors.gap import detect_gap, detect_gap_fill
from app.detectors.level_break import detect_level_break
from app.detectors.orb import detect_orb
from app.detectors.rvol import detect_rvol_spike
from app.detectors.trend import detect_trend
from app.detectors.types import DaySnapshot
from app.detectors.vwap_setups import detect_vwap_pullback, detect_vwap_reclaim
from app.models import Bar, CalendarDay, et_clock_to_utc

DAY = date(2026, 6, 16)
CAL = CalendarDay(DAY, "09:30", "16:00", "04:00", "20:00")
NO_LEVELS = Levels(None, None, None, None, None)


def rth(hhmm: str, o: float, h: float, l: float, c: float, vol: int = 1000) -> Bar:
    return Bar("SPY", et_clock_to_utc(DAY, hhmm), o, h, l, c, vol, "rth")


def snap(
    bars: list[Bar],
    prior_close: float | None = None,
    vwap: list | None = None,
    rvol: float | None = None,
    e9: list | None = None,
    e20: list | None = None,
    levels: Levels = NO_LEVELS,
) -> DaySnapshot:
    clock = bars[-1].ts if bars else et_clock_to_utc(DAY, "09:30")
    return DaySnapshot(
        symbol="SPY", cal=CAL, bars=bars, levels=levels, prior_close=prior_close,
        vwap=vwap or [], rvol=rvol, ema9_5m=e9 or [], ema20_5m=e20 or [], clock=clock,
    )


def _range_bars(start_min: int, end_min: int, low: float, high: float) -> list[Bar]:
    """RTH bars oscillating inside [low, high], minutes after 09:30."""
    out = []
    for m in range(start_min, end_min):
        hh, mm = divmod(9 * 60 + 30 + m, 60)
        px = low + (high - low) * ((m % 3) / 2)
        out.append(rth(f"{hh:02d}:{mm:02d}", px, min(px + 0.2, high), max(px - 0.2, low), px))
    return out


# --------------------------------------------------------------------- gap


def test_gap_fires_exactly_at_threshold():
    cfg = {"min_gap_pct": 2.0}
    exactly = snap([rth("09:30", 102.0, 102.5, 101.5, 102.0)], prior_close=100.0)
    assert detect_gap(exactly, cfg)[0].setup_type == "gap_up"
    just_under = snap([rth("09:30", 101.99, 102.5, 101.5, 102.0)], prior_close=100.0)
    assert detect_gap(just_under, cfg) == []


def test_gap_down_direction_and_context():
    s = snap([rth("09:30", 97.0, 97.5, 96.5, 97.0)], prior_close=100.0)
    sig = detect_gap(s, {"min_gap_pct": 2.0})[0]
    assert sig.setup_type == "gap_down" and sig.direction == "short"
    assert sig.context["gap_pct" ] == -3.0


def test_gap_fill_proposes_trade_toward_prior_close():
    bars = [
        rth("09:30", 103.0, 103.5, 102.5, 103.0),  # +3% gap up
        rth("09:31", 103.0, 103.4, 102.9, 103.1),  # still closing above the open
        rth("09:32", 103.1, 103.2, 102.0, 102.4),  # closes BELOW the open
    ]
    sig = detect_gap_fill(snap(bars, prior_close=100.0), {"min_gap_pct": 2.0})[0]
    assert sig.setup_type == "gap_fill" and sig.direction == "short"
    assert sig.target == 100.0
    assert sig.ts == bars[2].ts


# --------------------------------------------------------------------- orb


def test_orb_long_fires_on_first_close_beyond_range():
    bars = _range_bars(0, 15, 99.0, 101.0)
    bars.append(rth("09:45", 101.0, 101.8, 100.9, 101.5))  # close > OR high
    sig = detect_orb(snap(bars), {"minutes": 15})[0]
    assert sig.setup_type == "orb_long"
    assert sig.entry == 101.0 and sig.stop == 99.0 and sig.target == 105.0
    assert sig.rr == 2.0


def test_orb_needs_range_complete_and_a_real_close():
    inside = _range_bars(0, 15, 99.0, 101.0)
    assert detect_orb(snap(inside), {"minutes": 15}) == []  # nothing after OR yet
    wick_only = inside + [rth("09:45", 100.5, 101.6, 100.4, 100.9)]  # wick over, close in
    assert detect_orb(snap(wick_only), {"minutes": 15}) == []


def test_orb_short_mirrors():
    bars = _range_bars(0, 15, 99.0, 101.0)
    bars.append(rth("09:45", 99.0, 99.1, 98.2, 98.5))
    sig = detect_orb(snap(bars), {"minutes": 15})[0]
    assert sig.setup_type == "orb_short" and sig.entry == 99.0 and sig.stop == 101.0


# -------------------------------------------------------------------- vwap


def _flat_vwap(bars: list[Bar], value: float) -> list:
    return [(b.ts, value) for b in bars]


def test_vwap_reclaim_needs_full_hold():
    below = [rth(f"09:3{i}", 99.0, 99.3, 98.8, 99.0) for i in range(3)]
    two_above = below + [
        rth("09:33", 100.2, 100.4, 100.0, 100.3),
        rth("09:34", 100.3, 100.5, 100.1, 100.4),
    ]
    s2 = snap(two_above, vwap=_flat_vwap(two_above, 100.0))
    assert detect_vwap_reclaim(s2, {"reclaim_hold_bars": 3}) == []
    three_above = two_above + [rth("09:35", 100.4, 100.6, 100.2, 100.5)]
    s3 = snap(three_above, vwap=_flat_vwap(three_above, 100.0))
    sig = detect_vwap_reclaim(s3, {"reclaim_hold_bars": 3})[0]
    assert sig.setup_type == "vwap_reclaim" and sig.direction == "long"
    assert sig.ts == three_above[-1].ts


def test_vwap_reclaim_requires_having_lost_the_line():
    always_above = [rth(f"09:3{i}", 100.5, 100.8, 100.3, 100.6) for i in range(6)]
    s = snap(always_above, vwap=_flat_vwap(always_above, 100.0))
    assert detect_vwap_reclaim(s, {"reclaim_hold_bars": 3}) == []


def test_vwap_pullback_touch_and_hold_after_a_run():
    run = [rth(f"{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}", 100.6, 100.9, 100.4, 100.7) for i in range(12)]
    touch = rth("09:42", 100.4, 100.5, 99.9, 100.2)  # tags 100.0 vwap
    hold = [rth("09:43", 100.2, 100.5, 100.1, 100.4), rth("09:44", 100.4, 100.6, 100.2, 100.5)]
    bars = run + [touch] + hold
    s = snap(bars, vwap=_flat_vwap(bars, 100.0))
    sig = detect_vwap_pullback(s, {"reclaim_hold_bars": 3, "pullback_min_run_bars": 10})[0]
    assert sig.setup_type == "vwap_pullback" and sig.direction == "long"


# -------------------------------------------------------------- level break


def test_level_break_needs_prior_trading_inside():
    levels = Levels(105.0, 95.0, 100.0, None, None)
    inside_then_break = [
        rth("09:30", 104.0, 104.5, 103.5, 104.0),
        rth("09:31", 104.0, 105.4, 103.9, 105.2),
    ]
    sig = detect_level_break(snap(inside_then_break, levels=levels), {})[0]
    assert sig.setup_type == "level_break_pdh" and sig.entry == 105.0

    gapped_over = [
        rth("09:30", 106.0, 106.5, 105.5, 106.0),  # never traded below PDH today
        rth("09:31", 106.0, 106.4, 105.8, 106.2),
    ]
    assert detect_level_break(snap(gapped_over, levels=levels), {}) == []


# -------------------------------------------------------------- rvol / trend


def test_rvol_spike_exact_threshold():
    bars = [rth("09:30", 100.0, 100.5, 99.5, 100.2)]
    assert detect_rvol_spike(snap(bars, rvol=2.0), {"threshold": 2.0})[0].setup_type == "rvol_spike"
    assert detect_rvol_spike(snap(bars, rvol=1.99), {"threshold": 2.0}) == []


def test_trend_requires_persistent_alignment():
    ts_list = [et_clock_to_utc(DAY, f"09:{35 + 5 * i}") for i in range(4)]
    bars = [rth("09:30", 100, 100.5, 99.5, 100)]
    two = snap(bars, e9=[(t, 101.0) for t in ts_list[:2]], e20=[(t, 100.0) for t in ts_list[:2]])
    assert detect_trend(two, {}) == []
    three = snap(bars, e9=[(t, 101.0) for t in ts_list[:3]], e20=[(t, 100.0) for t in ts_list[:3]])
    sig = detect_trend(three, {})[0]
    assert sig.setup_type == "trend_up" and sig.ts == ts_list[2]
