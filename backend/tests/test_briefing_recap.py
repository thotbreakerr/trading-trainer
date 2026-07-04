"""Briefing builder + snapshot semantics, and the recap view — including the
computed-on-demand ledger for days the app never watched (doc §11, §16.8)."""
from __future__ import annotations

from datetime import date

from app.marketday.briefing import build_briefing, get_snapshot, save_snapshot
from app.marketday.recap import build_recap
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import FixedClock
from app.models import et_clock_to_utc, utcnow
from app.stores import journal as journal_store
from app.sim.engine import Trade
from tests.test_batch_golden import RULES, build_orb_day

ANCHOR = date(2026, 6, 16)


def test_briefing_cards_focus_and_key_times(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    cal_day = calendar.day(ANCHOR)
    clock = FixedClock(et_clock_to_utc(ANCHOR, "09:25"))  # pre-open
    briefing = build_briefing(
        conn, calendar, ["SPY"], {"opening_range_breakout"}, cal_day, clock, utcnow()
    )
    card = briefing["cards"][0]
    assert card["symbol"] == "SPY"
    assert card["prior_high"] == 100.8 and card["prior_close"] == 100.0
    assert card["premarket_high"] == 100.6 and card["premarket_low"] == 99.4
    assert card["gap_pct"] is not None
    assert card["nearest_level"]["name"] in ("PDC", "PDH", "PDL", "PMH", "PML")
    assert briefing["focus"] and briefing["focus"][0]["symbol"] == "SPY"
    times = briefing["game_plan"]["key_times"]
    assert times["or_complete"]["et"] == "9:45 AM"
    assert times["close"]["ct"] == "3:00 PM"  # 16:00 ET on a full day
    assert "opening_range_breakout" in briefing["game_plan"]["setups_in_play"]


def test_briefing_snapshot_saved_once(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    cal_day = calendar.day(ANCHOR)
    clock = FixedClock(et_clock_to_utc(ANCHOR, "09:25"))
    built = build_briefing(conn, calendar, ["SPY"], set(), cal_day, clock, utcnow())
    save_snapshot(conn, built)
    snap = get_snapshot(conn, ANCHOR.isoformat())
    assert snap is not None and snap["day"] == ANCHOR.isoformat()


def test_recap_computes_ledger_on_demand(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    recap = build_recap(conn, calendar, RULES, ["SPY"], ANCHOR)
    assert recap["ledger_computed_on_demand"] is True
    orb = next(i for i in recap["ledger"] if i["setup_type"] == "orb_long")
    assert orb["outcome"] == "target" and orb["outcome_r"] == 2.0
    assert "computed on demand" in orb["note"]
    assert recap["plan_vs_reality"]["taken"] is False
    assert recap["trades"] == []


def test_recap_with_briefing_and_trades(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    cal_day = calendar.day(ANCHOR)
    briefing = build_briefing(
        conn, calendar, ["SPY"], set(), cal_day, FixedClock(et_clock_to_utc(ANCHOR, "09:25")), utcnow()
    )
    save_snapshot(conn, briefing)
    trade = Trade(
        id=1, symbol="SPY", direction="long", qty=100,
        entry_ts=et_clock_to_utc(ANCHOR, "09:50"), entry_price=100.5,
        stop_price=99.7,
        exit_ts=et_clock_to_utc(ANCHOR, "10:20"), exit_price=102.1,
        exit_reason="target", r_multiple=2.0,
    )
    journal_store.insert_closed_trade(conn, "marketday", ANCHOR, trade)

    recap = build_recap(conn, calendar, RULES, ["SPY"], ANCHOR)
    assert recap["plan_vs_reality"]["taken"] is True
    reality = recap["plan_vs_reality"]["reality"][0]
    assert reality["symbol"] == "SPY" and reality["broke_pdh"] is True
    trade_row = recap["trades"][0]
    assert trade_row["r_multiple"] == 2.0
    assert trade_row["review"]["symbol"] == "SPY"  # jump-back payload
    assert recap["trajectory"]["cumulative"]["trades"] == 1