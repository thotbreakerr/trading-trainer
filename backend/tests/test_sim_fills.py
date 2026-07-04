"""The fill matrix (doc §9) — every worst-case rule as a unit test. Pure
engine, no DB, hand-built bars."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import Bar, CalendarDay, et_clock_to_utc
from app.sim.engine import SimEngine

DAY = date(2026, 6, 16)
CAL = CalendarDay(DAY, "09:30", "16:00", "04:00", "20:00")


def bar(hhmm: str, o: float, h: float, l: float, c: float) -> Bar:
    return Bar("SPY", et_clock_to_utc(DAY, hhmm), o, h, l, c, 1000, "rth")


def ts(hhmm: str):
    return et_clock_to_utc(DAY, hhmm)


def engine() -> SimEngine:
    return SimEngine(starting_balance=30_000)


def prime(sim: SimEngine, close: float = 100.0) -> None:
    """Reveal one bar so market orders have a reference price."""
    sim.on_bar(bar("09:30", close, close + 0.5, close - 0.5, close))


# 1. market -> next bar's open --------------------------------------------


def test_market_order_fills_at_next_bar_open_long_and_short():
    sim = engine()
    prime(sim, 100.0)
    order, events = sim.place_order(ts("09:31"), "SPY", "buy", "market", 10)
    assert not events
    fills = sim.on_bar(bar("09:31", 101.0, 101.5, 100.5, 101.2))
    assert order.fill_price == 101.0 and order.status == "filled"
    assert fills[0].kind == "fill"
    assert sim.positions["SPY"].qty == 10

    sim2 = engine()
    prime(sim2, 100.0)
    short, _ = sim2.place_order(ts("09:31"), "SPY", "sell", "market", 10)
    sim2.on_bar(bar("09:31", 99.0, 99.5, 98.5, 99.2))
    assert short.fill_price == 99.0
    assert sim2.positions["SPY"].qty == -10


def test_market_order_never_fills_before_placement():
    sim = engine()
    prime(sim, 100.0)
    order, _ = sim.place_order(ts("09:35"), "SPY", "buy", "market", 10)
    sim.on_bar(bar("09:34", 100.0, 100.5, 99.5, 100.2))  # earlier bar: no fill
    assert order.status == "working"


# 2. market with no next bar cancels at EOD --------------------------------


def test_market_order_with_no_next_bar_cancels_at_eod():
    sim = engine()
    prime(sim, 100.0)
    order, _ = sim.place_order(ts("15:59"), "SPY", "buy", "market", 10)
    events = sim.on_clock(ts("16:00"), CAL)
    assert order.status == "canceled" and order.reason == "end of day"
    assert order.fill_price is None
    assert not any(e.kind == "fill" for e in events)


# 3. limits: traded through vs gapped through ------------------------------


def test_buy_limit_fills_at_limit_when_traded_through():
    sim = engine()
    order, _ = sim.place_order(ts("09:31"), "SPY", "buy", "limit", 10, limit_price=100.0)
    sim.on_bar(bar("09:31", 101.0, 101.2, 99.5, 100.8))
    assert order.fill_price == 100.0


def test_buy_limit_gapped_through_fills_at_open():
    sim = engine()
    order, _ = sim.place_order(ts("09:31"), "SPY", "buy", "limit", 10, limit_price=100.0)
    sim.on_bar(bar("09:31", 99.0, 99.8, 98.5, 99.5))
    assert order.fill_price == 99.0  # the real opening print, better than limit


def test_sell_limit_mirrors():
    sim = engine()
    prime(sim, 100.0)
    entry, _ = sim.place_order(ts("09:31"), "SPY", "buy", "market", 10)
    sim.on_bar(bar("09:31", 100.0, 100.5, 99.5, 100.0))
    exit_order, _ = sim.place_order(ts("09:32"), "SPY", "sell", "limit", 10, limit_price=101.0)
    sim.on_bar(bar("09:32", 101.5, 102.0, 101.0, 101.8))  # opens above the limit
    assert exit_order.fill_price == 101.5


# 4. untouched limit cancels at EOD ----------------------------------------


def test_untouched_limit_cancels_at_eod():
    sim = engine()
    order, _ = sim.place_order(ts("09:31"), "SPY", "buy", "limit", 10, limit_price=90.0)
    sim.on_bar(bar("09:31", 100.0, 100.5, 99.5, 100.0))
    sim.on_clock(ts("16:00"), CAL)
    assert order.status == "canceled" and order.reason == "end of day"


# 5. stops: cross vs gap ----------------------------------------------------


def _long_with_bracket(sim: SimEngine, stop: float, target: float):
    prime(sim, 100.0)
    orders, events = sim.place_bracket(
        ts("09:31"), "SPY", "buy", 10, stop_price=stop, target_price=target
    )
    assert not events
    sim.on_bar(bar("09:31", 100.0, 100.4, 99.8, 100.2))  # entry fills at 100
    assert sim.positions["SPY"].qty == 10
    return orders  # [entry, stop, target]


def test_stop_fills_at_stop_price_on_cross():
    sim = engine()
    _, stop, _ = _long_with_bracket(sim, stop=99.0, target=103.0)
    sim.on_bar(bar("09:32", 99.5, 99.6, 98.8, 99.0))
    assert stop.status == "filled" and stop.fill_price == 99.0


def test_stop_gapped_past_fills_at_bar_open():
    sim = engine()
    _, stop, _ = _long_with_bracket(sim, stop=99.0, target=103.0)
    sim.on_bar(bar("09:32", 97.5, 98.0, 97.0, 97.8))  # gapped below the stop
    assert stop.fill_price == 97.5  # doc-explicit: worse price, honestly


def test_short_stop_mirrors_with_gap():
    sim = engine()
    prime(sim, 100.0)
    sim.place_bracket(ts("09:31"), "SPY", "sell", 10, stop_price=101.0, target_price=97.0)
    sim.on_bar(bar("09:31", 100.0, 100.4, 99.8, 100.0))  # short entry at 100
    sim.on_bar(bar("09:32", 102.0, 102.5, 101.5, 102.2))  # gaps above stop
    stop = next(o for o in sim.orders.values() if o.role == "stop")
    assert stop.fill_price == 102.0


# 6. same-bar stop + target: the stop is assumed ----------------------------


def test_same_bar_stop_and_target_resolves_to_stop_long():
    sim = engine()
    _, stop, target = _long_with_bracket(sim, stop=99.0, target=101.0)
    sim.on_bar(bar("09:32", 100.0, 101.5, 98.5, 100.5))  # touches BOTH
    assert stop.status == "filled" and stop.fill_price == 99.0
    assert target.status == "canceled" and "OCO" in (target.reason or "")
    assert sim.trades[-1].exit_reason == "stop"


def test_same_bar_stop_and_target_resolves_to_stop_short():
    sim = engine()
    prime(sim, 100.0)
    sim.place_bracket(ts("09:31"), "SPY", "sell", 10, stop_price=101.0, target_price=99.0)
    sim.on_bar(bar("09:31", 100.0, 100.2, 99.8, 100.0))
    sim.on_bar(bar("09:32", 100.0, 101.5, 98.5, 100.0))
    stop = next(o for o in sim.orders.values() if o.role == "stop")
    target = next(o for o in sim.orders.values() if o.role == "target")
    assert stop.status == "filled" and target.status == "canceled"


# 7. entry and exit inside one bar ------------------------------------------


def test_bracket_entry_and_stop_fill_in_same_bar():
    sim = engine()
    prime(sim, 100.0)
    sim.place_bracket(ts("09:31"), "SPY", "buy", 10, stop_price=99.0, target_price=103.0)
    events = sim.on_bar(bar("09:31", 100.0, 100.2, 98.5, 99.2))  # fills entry, then stop
    assert len([e for e in events if e.kind == "fill"]) == 2
    assert "SPY" not in sim.positions
    assert sim.trades[-1].exit_reason == "stop"


def test_bracket_entry_and_target_fill_in_same_bar_when_stop_untouched():
    sim = engine()
    prime(sim, 100.0)
    sim.place_bracket(ts("09:31"), "SPY", "buy", 10, stop_price=99.0, target_price=100.5)
    sim.on_bar(bar("09:31", 100.0, 101.0, 99.5, 100.8))  # target in range, stop not
    assert sim.trades[-1].exit_reason == "target"
    assert sim.trades[-1].exit_price == 100.5


# 8. OCO + whole-bracket EOD cancel -----------------------------------------


def test_target_fill_cancels_stop():
    sim = engine()
    _, stop, target = _long_with_bracket(sim, stop=99.0, target=101.0)
    sim.on_bar(bar("09:32", 100.5, 101.2, 100.2, 101.0))
    assert target.status == "filled" and stop.status == "canceled"


def test_unfilled_bracket_evaporates_at_eod():
    sim = engine()
    prime(sim, 100.0)
    orders, _ = sim.place_bracket(
        ts("09:31"), "SPY", "buy", 10, stop_price=94.0, target_price=99.0,
        entry_type="limit", limit_price=95.0,
    )
    sim.on_bar(bar("09:31", 100.0, 100.5, 99.5, 100.0))  # never reaches 95
    sim.on_clock(ts("16:00"), CAL)
    assert all(o.status == "canceled" for o in orders)


# 9. buying power ------------------------------------------------------------


def test_buying_power_breach_rejects_cleanly():
    sim = engine()  # 30k * 4 = 120k
    prime(sim, 130.0)
    order, events = sim.place_order(ts("09:31"), "SPY", "buy", "market", 1000)  # 130k
    assert order.status == "rejected"
    assert events[0].kind == "reject" and "buying power" in events[0].detail
    assert not sim.orders[order.id].status == "working"


def test_buying_power_exactly_at_limit_passes():
    sim = engine()
    prime(sim, 120.0)
    order, events = sim.place_order(ts("09:31"), "SPY", "buy", "market", 1000)  # 120k
    assert not events and order.status == "working"


# 11. sparse minutes ----------------------------------------------------------


def test_resting_orders_survive_missing_minutes():
    sim = engine()
    order, _ = sim.place_order(ts("09:31"), "SPY", "buy", "limit", 10, limit_price=99.0)
    sim.on_bar(bar("09:31", 100.0, 100.2, 99.8, 100.0))
    # minutes 09:32-09:40 never trade — next real bar crosses the limit
    sim.on_bar(bar("09:41", 99.5, 99.6, 98.9, 99.2))
    assert order.status == "filled" and order.fill_price == 99.0


# 12. R-multiples -------------------------------------------------------------


@pytest.mark.parametrize(
    "side,stop,target,exit_bar,expected_r,expected_reason",
    [
        ("buy", 99.0, 102.0, bar("09:32", 101.0, 102.5, 100.8, 102.0), 2.0, "target"),
        ("buy", 99.0, 103.0, bar("09:32", 99.5, 99.6, 98.7, 99.0), -1.0, "stop"),
        ("sell", 101.0, 98.0, bar("09:32", 99.0, 99.2, 97.5, 98.0), 2.0, "target"),
    ],
)
def test_r_multiples_signed_correctly(side, stop, target, exit_bar, expected_r, expected_reason):
    sim = engine()
    prime(sim, 100.0)
    sim.place_bracket(ts("09:31"), "SPY", side, 10, stop_price=stop, target_price=target)
    sim.on_bar(bar("09:31", 100.0, 100.2, 99.8, 100.0))  # entry at 100
    sim.on_bar(exit_bar)
    trade = sim.trades[-1]
    assert trade.exit_reason == expected_reason
    assert trade.r_multiple == pytest.approx(expected_r)


def test_forced_eod_close_r_is_a_scratch():
    sim = engine()
    _long_with_bracket(sim, stop=99.0, target=105.0)
    sim.on_bar(bar("15:59", 100.4, 100.6, 100.3, 100.5))
    sim.on_clock(ts("16:00"), CAL)
    trade = sim.trades[-1]
    assert trade.exit_reason == "eod"
    assert trade.r_multiple == pytest.approx(0.5)  # +0.50 on a $1 risk


# 13. one position per symbol -------------------------------------------------


def test_second_entry_rejected_while_position_open():
    sim = engine()
    _long_with_bracket(sim, stop=99.0, target=103.0)
    order, events = sim.place_order(ts("09:33"), "SPY", "buy", "market", 5)
    assert order.status == "rejected"
    assert "one position per symbol" in events[0].detail


def test_second_entry_rejected_while_first_still_working():
    sim = engine()
    prime(sim, 100.0)
    sim.place_order(ts("09:31"), "SPY", "buy", "limit", 10, limit_price=99.0)
    order, events = sim.place_order(ts("09:31"), "SPY", "buy", "market", 5)
    assert order.status == "rejected"
    assert "already working" in events[0].detail
