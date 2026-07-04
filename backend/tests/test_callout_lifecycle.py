"""Callout state machine (doc §11): fired -> watching -> invalidated/expired,
locked teasers, missed-window marking, hindsight completion, user action."""
from __future__ import annotations

from datetime import date, timedelta

from app.grading.grader import GradeResult
from app.marketday.callouts import CalloutEngine
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, ReplayClock
from app.models import Bar, CalendarDay, DailyBar, et_clock_to_utc
from app.stores import setups as setups_store
from tests.test_batch_golden import RULES, build_orb_day

ANCHOR = date(2026, 6, 16)


def make_engine(unlocked=frozenset()) -> CalloutEngine:
    return CalloutEngine(rules_cfg=RULES | {"unlocks": {"opening_range_breakout": 8}},
                         unlocked=set(unlocked))


def drive(conn, engine, until_hhmm: str, step_min: int = 1):
    calendar = MarketCalendar(conn)
    cal_day = calendar.day(ANCHOR)
    clock = ReplayClock(cal_day.open_utc())
    window = BarWindow(conn, calendar, clock, ANCHOR, lookback_days=1)
    end = et_clock_to_utc(ANCHOR, until_hhmm)
    events = []
    while clock.current < end:
        clock.current += timedelta(minutes=step_min)
        events += engine.on_tick(conn, window, ["SPY"], ANCHOR)
    return events, clock, window


def test_fire_watch_expire_and_hindsight(conn):
    build_orb_day(conn)
    engine = make_engine(unlocked={"opening_range_breakout"})
    events, clock, window = drive(conn, engine, "10:05")

    fired = [e for e in events if e["kind"] == "callout_fired"]
    orb = next(e["callout"] for e in fired if e["callout"].get("setup_type") == "orb_long")
    assert orb["locked"] is False
    assert orb["grade"] is not None

    expired = [e for e in events if e["kind"] == "callout_expired"]
    assert any(e["callout"].get("setup_type") == "orb_long" for e in expired), (
        "10-minute watch window must expire untouched"
    )
    # drive to the close: hindsight resolves to the target on the ramp day
    drive_events, clock, window = drive(conn, engine, "16:01")
    callout = next(
        c for c in engine.callouts.values() if c.signal.setup_type == "orb_long"
    )
    assert callout.outcome == "target"
    assert callout.outcome_r == 2.0
    rows = setups_store.list_setups(conn, ANCHOR, mode="marketday")
    row = next(r for r in rows if r["setup_type"] == "orb_long")
    assert row["outcome"] == "target" and row["outcome_r"] == 2.0


def test_locked_concepts_fire_as_teasers(conn):
    build_orb_day(conn)
    engine = make_engine(unlocked=set())  # nothing unlocked
    events, clock, _ = drive(conn, engine, "10:00")
    fired = [e["callout"] for e in events if e["kind"] == "callout_fired"]
    assert fired and all(c["locked"] for c in fired)
    teaser = fired[0]
    assert "setup_type" not in teaser  # the tease hides WHAT fired
    assert "entry" not in teaser
    rows = setups_store.list_setups(conn, ANCHOR, mode="marketday")
    assert rows, "locked fires still land in the ledger (doc §12)"


def _invalidation_day(conn) -> None:
    """OR breakout at 09:45 that immediately breaks its own stop."""
    prior = date(2026, 6, 15)
    cal = [CalendarDay(d, "09:30", "16:00", "04:00", "20:00") for d in (prior, ANCHOR)]
    store.upsert_calendar(conn, cal)
    store.upsert_bars_daily(conn, [DailyBar("SPY", prior, 99.5, 108.0, 92.0, 100.0, 1)])
    bars = [Bar("SPY", et_clock_to_utc(prior, "09:30"), 99.5, 108.0, 92.0, 100.0, 1000, "rth")]
    for m in range(15):
        hh, mm = divmod(9 * 60 + 30 + m, 60)
        px = 100.0 + (m % 2) * 0.3
        bars.append(Bar("SPY", et_clock_to_utc(ANCHOR, f"{hh:02d}:{mm:02d}"),
                        px, px + 0.2, px - 0.2, px, 40_000, "rth"))
    bars.append(Bar("SPY", et_clock_to_utc(ANCHOR, "09:45"), 100.3, 101.0, 100.2, 100.8, 90_000, "rth"))
    bars.append(Bar("SPY", et_clock_to_utc(ANCHOR, "09:47"), 100.5, 100.6, 99.5, 99.6, 90_000, "rth"))
    store.upsert_bars_1m(conn, bars)
    for d in (prior, ANCHOR):
        cd = cal[0] if d == prior else cal[1]
        store.mark_day_cached(conn, "SPY", d, cd.session_close_utc() + timedelta(hours=1))


def test_invalidation_flips_the_card(conn):
    _invalidation_day(conn)
    engine = make_engine(unlocked={"opening_range_breakout"})
    events, clock, _ = drive(conn, engine, "09:50")
    invalidated = [e for e in events if e["kind"] == "callout_invalidated"]
    assert invalidated, "stop-level break during the watch window must invalidate"
    card = invalidated[0]["callout"]
    assert "trap" in (card["invalidated_reason"] or "")
    rows = setups_store.list_setups(conn, ANCHOR, mode="marketday")
    assert any(r["status"] == "invalidated" for r in rows)


def test_missed_window_marks_ledger(conn):
    build_orb_day(conn)
    engine = make_engine(unlocked={"opening_range_breakout"})
    calendar = MarketCalendar(conn)
    cal_day = calendar.day(ANCHOR)
    clock = ReplayClock(et_clock_to_utc(ANCHOR, "15:30"))  # app opened late
    window = BarWindow(conn, calendar, clock, ANCHOR, lookback_days=1)
    events = engine.on_tick(conn, window, ["SPY"], ANCHOR)
    fired = [e for e in events if e["kind"] == "callout_fired"]
    assert fired and all(e["sound"] is False for e in fired)  # no alert spam
    rows = setups_store.list_setups(conn, ANCHOR, mode="marketday")
    orb = next(r for r in rows if r["setup_type"] == "orb_long")
    assert orb["status"] == "expired"
    assert orb["note"] == "missed (app closed)"


def test_mark_acted_records_user_decision(conn):
    build_orb_day(conn)
    engine = make_engine(unlocked={"opening_range_breakout"})
    events, clock, _ = drive(conn, engine, "09:50")
    callout = next(c for c in engine.callouts.values() if c.signal.setup_type == "orb_long")
    grade = GradeResult("Solid", [], None)
    engine.mark_acted(conn, callout, clock.current, grade)
    assert callout.status == "acted"
    row = next(
        r for r in setups_store.list_setups(conn, ANCHOR, mode="marketday")
        if r["setup_type"] == "orb_long"
    )
    assert row["taken"] == 1 and row["user_grade"] == "Solid"