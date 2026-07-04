"""Hindsight outcome tracking (doc §11.4) — pure, worst-case biased."""
from __future__ import annotations

from datetime import date

import pytest

from app.marketday.hindsight import track_outcome
from app.models import Bar, et_clock_to_utc

DAY = date(2026, 6, 16)


def bar(hhmm: str, o, h, l, c) -> Bar:
    return Bar("SPY", et_clock_to_utc(DAY, hhmm), o, h, l, c, 1000, "rth")


def test_target_after_trigger():
    bars = [
        bar("09:46", 100.5, 100.6, 100.3, 100.5),  # entry 100.4 touched
        bar("09:47", 100.5, 102.1, 100.4, 102.0),  # target 102 touched
    ]
    out = track_outcome(bars, "long", 100.4, 99.6, 102.0)
    assert out.outcome == "target" and out.r_multiple == pytest.approx(2.0)


def test_stop_wins_shared_bar():
    bars = [
        bar("09:46", 100.5, 102.5, 99.5, 101.0),  # touches entry, stop AND target
    ]
    out = track_outcome(bars, "long", 100.4, 99.6, 102.0)
    assert out.outcome == "stop" and out.r_multiple == pytest.approx(-1.0)


def test_never_triggered():
    bars = [bar("09:46", 99.0, 99.3, 98.8, 99.0)]  # never reaches entry 100.4
    out = track_outcome(bars, "long", 100.4, 99.6, 102.0)
    assert out.outcome == "never_triggered" and out.r_multiple is None


def test_eod_close_r():
    bars = [
        bar("09:46", 100.5, 100.6, 100.3, 100.5),
        bar("15:59", 101.0, 101.1, 100.9, 101.2),  # neither side hit by the close
    ]
    out = track_outcome(bars, "long", 100.4, 99.6, 102.0)
    assert out.outcome == "eod"
    assert out.r_multiple == pytest.approx((101.2 - 100.4) / 0.8, abs=1e-3)


def test_short_mirrors():
    bars = [
        bar("09:46", 99.5, 99.7, 99.4, 99.5),  # short entry 99.6 touched
        bar("09:47", 99.4, 99.5, 97.9, 98.0),  # target 98.0 touched
    ]
    out = track_outcome(bars, "short", 99.6, 100.4, 98.0)
    assert out.outcome == "target" and out.r_multiple == pytest.approx(2.0)