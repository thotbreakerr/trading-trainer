"""EOD discipline (doc §9) + sizing: warn window, forced flatten at the
calendar close (half days included), account restarts."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import Bar, CalendarDay, et_clock_to_utc
from app.sim.engine import SimEngine
from app.sim.sizing import SizingError, size_position

DAY = date(2026, 6, 16)
FULL = CalendarDay(DAY, "09:30", "16:00", "04:00", "20:00")
HALF_DAY = date(2026, 11, 27)
HALF = CalendarDay(HALF_DAY, "09:30", "13:00", "04:00", "20:00")


def bar(hhmm: str, px: float, d: date = DAY) -> Bar:
    return Bar("SPY", et_clock_to_utc(d, hhmm), px, px + 0.2, px - 0.2, px, 1000, "rth")


def open_long(sim: SimEngine, d: date = DAY) -> None:
    sim.on_bar(bar("09:30", 100.0, d))
    sim.place_bracket(
        et_clock_to_utc(d, "09:31"), "SPY", "buy", 10, stop_price=95.0, target_price=110.0
    )
    sim.on_bar(bar("09:31", 100.0, d))
    assert sim.positions


@pytest.mark.parametrize(
    "cal,d,warn_hhmm,close_hhmm",
    [(FULL, DAY, "15:50", "16:00"), (HALF, HALF_DAY, "12:50", "13:00")],
    ids=["full-day", "half-day"],
)
def test_warning_then_forced_flatten_times_come_from_calendar(cal, d, warn_hhmm, close_hhmm):
    sim = SimEngine(30_000)
    open_long(sim, d)

    before = sim.on_clock(et_clock_to_utc(d, "12:00") if cal is FULL else et_clock_to_utc(d, "11:00"), cal)
    assert not any(e.kind == "eod_warning" for e in before)

    warn = sim.on_clock(et_clock_to_utc(d, warn_hhmm), cal)
    assert any(e.kind == "eod_warning" for e in warn)
    again = sim.on_clock(et_clock_to_utc(d, warn_hhmm), cal)
    assert not any(e.kind == "eod_warning" for e in again)  # warn once

    flatten = sim.on_clock(et_clock_to_utc(d, close_hhmm), cal)
    flat_events = [e for e in flatten if e.kind == "eod_flatten"]
    assert flat_events and "forced EOD close" in flat_events[0].detail
    assert not sim.positions and sim.flattened
    assert sim.trades[-1].exit_reason == "eod"


def test_no_warning_without_a_position():
    sim = SimEngine(30_000)
    sim.on_bar(bar("09:30", 100.0))
    events = sim.on_clock(et_clock_to_utc(DAY, "15:50"), FULL)
    assert events == []


def test_orders_rejected_after_flatten():
    sim = SimEngine(30_000)
    open_long(sim)
    sim.on_bar(bar("15:59", 101.0))
    sim.on_clock(et_clock_to_utc(DAY, "16:00"), FULL)
    order, events = sim.place_order(et_clock_to_utc(DAY, "16:01"), "SPY", "buy", "market", 5)
    assert order.status == "rejected"
    assert "past the close" in events[0].detail


def test_flatten_cash_matches_last_close():
    sim = SimEngine(30_000)
    open_long(sim)  # 10 @ 100 -> cash 29_000
    sim.on_bar(bar("15:59", 104.0))
    sim.on_clock(et_clock_to_utc(DAY, "16:00"), FULL)
    assert sim.cash == pytest.approx(30_000 + 10 * 4.0)  # +$40 P&L
    assert sim.equity() == pytest.approx(sim.cash)


# ------------------------------------------------------------------- sizing


def test_sizing_floors_to_whole_shares():
    s = size_position(equity=30_000, entry=100.0, stop=99.53, risk_pct=1.0)
    assert s.shares == 638  # 300 / 0.47 = 638.29…
    assert s.risk_amount == pytest.approx(638 * 0.47)
    assert not s.bp_capped


def test_sizing_rejects_stop_at_entry():
    with pytest.raises(SizingError):
        size_position(equity=30_000, entry=100.0, stop=100.0)


def test_sizing_caps_at_buying_power():
    s = size_position(equity=30_000, entry=100.0, stop=99.99, risk_pct=1.0, leverage=4.0)
    assert s.shares == 1200  # BP cap: 120k / 100, not the 30k risk shares
    assert s.bp_capped
