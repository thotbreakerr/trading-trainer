"""Grader tiers (doc §10): pass-count mapping, the RVOL-confluence trap rule,
and the acted-after-invalidation override."""
from __future__ import annotations

from datetime import date

from app.analysis.levels import Levels
from app.detectors.types import DaySnapshot
from app.grading.grader import grade_entry, tier_at_least
from app.models import Bar, CalendarDay, et_clock_to_utc

DAY = date(2026, 6, 16)
CAL = CalendarDay(DAY, "09:30", "16:00", "04:00", "20:00")
GRADING = {"min_rr": 2.0, "min_rvol": 1.5}


def rth(hhmm: str, o: float, h: float, l: float, c: float) -> Bar:
    return Bar("SPY", et_clock_to_utc(DAY, hhmm), o, h, l, c, 1000, "rth")


def make_snap(rvol: float | None = 2.0, trend: str = "long") -> DaySnapshot:
    # last close 100.0, recent swing low ~99.4 / high ~100.6
    bars = [rth(f"09:3{i}", 100.0, 100.6, 99.4, 100.0) for i in range(6)]
    fast, slow = (101.0, 100.0) if trend == "long" else (100.0, 101.0)
    pts = [(b.ts, fast) for b in bars[-3:]]
    pts20 = [(b.ts, slow) for b in bars[-3:]]
    return DaySnapshot(
        symbol="SPY", cal=CAL, bars=bars, levels=Levels(None, None, None, None, None),
        prior_close=99.0, vwap=[], rvol=rvol, ema9_5m=pts, ema20_5m=pts20,
        clock=bars[-1].ts,
    )


def test_all_five_passes_is_textbook():
    g = grade_entry("long", 100.0, 99.3, 101.4, make_snap(), GRADING)
    assert [i.passed for i in g.checklist] == [True] * 5
    assert g.tier == "Textbook"


def test_missing_only_rvol_is_solid_and_flags_breakout_traps():
    g = grade_entry("long", 100.0, 99.3, 101.4, make_snap(rvol=1.0), GRADING)
    assert g.tier == "Solid"
    assert g.note is None  # not a breakout setup
    trap = grade_entry(
        "long", 100.0, 99.3, 101.4, make_snap(rvol=1.0), GRADING, setup_type="orb_long"
    )
    assert trap.tier == "Solid"
    assert "trap" in (trap.note or "")


def test_three_passes_is_risky_two_is_reckless():
    # counter-trend (miss) + thin volume (miss): 3 passes -> Risky
    risky = grade_entry("short", 100.0, 100.7, 98.6, make_snap(rvol=1.0, trend="long"), GRADING)
    assert sum(i.passed for i in risky.checklist) == 3
    assert risky.tier == "Risky"
    # additionally bad R:R: 2 passes -> Reckless
    reckless = grade_entry("short", 100.0, 100.7, 99.4, make_snap(rvol=1.0, trend="long"), GRADING)
    assert sum(i.passed for i in reckless.checklist) == 2
    assert reckless.tier == "Reckless"


def test_invalidated_setup_is_reckless_with_reason():
    g = grade_entry(
        "long", 100.0, 99.3, 101.4, make_snap(), GRADING, invalidated=True
    )
    assert g.tier == "Reckless"
    assert "invalidated" in (g.note or "")


def test_chasing_far_from_entry_fails_the_chase_item():
    # entry reference 2R away from the last price
    g = grade_entry("long", 98.0, 97.3, 99.4, make_snap(), GRADING)
    chase = next(i for i in g.checklist if i.key == "chase")
    assert not chase.passed


def test_tier_ordering_helper():
    assert tier_at_least("Textbook", "Solid")
    assert tier_at_least("Solid", "Solid")
    assert not tier_at_least("Risky", "Solid")
