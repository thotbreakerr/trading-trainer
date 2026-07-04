"""Golden signal set on a CONSTRUCTED day (doc §17.6): a hand-built ORB
session where every expected fire is known, plus the incremental ≡ batch
equivalence guarantee ('same engine in both modes', doc §10).

The day, by construction:
- No gap (opens exactly at the prior close).
- 09:30-09:44 opening range 99.6-100.4, oscillating across VWAP.
- 09:45 breakout bar closes 100.9: above the OR high AND the prior-day high
  (100.8) -> orb_long and level_break_pdh both fire at 09:45.
- The ramp then holds above VWAP -> one vwap_reclaim; 5m EMAs align -> one
  trend_up. Lows never tag VWAP again -> NO vwap_pullback. No rvol baseline
  is seeded -> NO rvol_spike.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.detectors.engine import live_signals, scan_day
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, ReplayClock, RvolBaseline
from app.models import ET, Bar, CalendarDay, DailyBar, et_clock_to_utc

PRIOR = date(2026, 6, 15)
ANCHOR = date(2026, 6, 16)
RULES = {
    "detectors": {
        "gap": {"min_gap_pct": 2.0},
        "opening_range": {"minutes": 15},
        "vwap": {"reclaim_hold_bars": 3, "pullback_min_run_bars": 10},
        "level_break": {},
        "rvol_spike": {"threshold": 2.0},
        "trend": {},
    }
}


def _cd(d: date) -> CalendarDay:
    return CalendarDay(d, "09:30", "16:00", "04:00", "20:00")


def _bar(d: date, hhmm: str, o, h, l, c, vol=50_000, session="rth") -> Bar:
    return Bar("SPY", et_clock_to_utc(d, hhmm), o, h, l, c, vol, session)


def _minute(m: int) -> str:
    hh, mm = divmod(9 * 60 + 30 + m, 60)
    return f"{hh:02d}:{mm:02d}"


def build_orb_day(conn) -> None:
    store.upsert_calendar(conn, [_cd(PRIOR), _cd(ANCHOR)])
    store.upsert_bars_daily(
        conn, [DailyBar("SPY", PRIOR, 99.5, 100.8, 99.2, 100.0, 10_000_000)]
    )
    bars: list[Bar] = [
        _bar(PRIOR, "09:30", 99.5, 100.8, 99.2, 100.0),  # prior day (one bar is enough)
        # pre-market range ENCLOSES the OR so PMH/PML never break before the
        # breakout bar (and PDH > PMH, so the PDH break wins the direction)
        _bar(ANCHOR, "09:00", 100.0, 100.6, 99.4, 100.0, 5_000, "pre"),
    ]
    # 09:30-09:44: the opening range, oscillating across its own VWAP
    for m in range(15):
        if m % 2 == 0:
            bars.append(_bar(ANCHOR, _minute(m), 100.0, 100.4, 99.9, 100.3))
        else:
            bars.append(_bar(ANCHOR, _minute(m), 100.3, 100.1 + 0.1, 99.6, 99.7))
    # 09:45: the breakout bar (closes over OR high 100.4 AND PDH 100.8)
    bars.append(_bar(ANCHOR, "09:45", 100.4, 101.0, 100.3, 100.9, 150_000))
    # ramp: strictly above VWAP, higher highs
    px = 100.9
    for m in range(16, 61):
        nxt = round(px + 0.05, 2)
        bars.append(_bar(ANCHOR, _minute(m), px, nxt + 0.05, px - 0.02, nxt, 80_000))
        px = nxt
    store.upsert_bars_1m(conn, bars)
    for d in (PRIOR, ANCHOR):
        store.mark_day_cached(conn, "SPY", d, _cd(d).session_close_utc() + timedelta(hours=1))


def _summarize(signals):
    return [
        (
            s.setup_type,
            s.direction,
            s.ts.astimezone(ET).strftime("%H:%M"),
            s.entry,
            s.stop,
        )
        for s in signals
    ]


def test_constructed_orb_day_fires_the_exact_golden_set(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    signals = scan_day(conn, calendar, "SPY", ANCHOR, RULES)
    got = _summarize(signals)
    # signal.ts is the CONFIRMING BAR's start (09:45), visible at clock 09:46
    assert ("orb_long", "long", "09:45", 100.4, 99.6) in got
    assert ("level_break_pdh", "long", "09:45", 100.8, 99.6) in got
    types = [g[0] for g in got]
    assert types.count("orb_long") == 1
    assert types.count("level_break_pdh") == 1
    assert types.count("vwap_reclaim") == 1
    assert types.count("trend_up") == 1
    assert "vwap_pullback" not in types  # lows never tag VWAP after the run
    assert "rvol_spike" not in types  # no baseline seeded
    assert "gap_up" not in types and "gap_fill" not in types
    assert len(got) == 4, got


def test_incremental_equals_batch(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    batch = scan_day(conn, calendar, "SPY", ANCHOR, RULES)

    cal_day = calendar.day(ANCHOR)
    clock = ReplayClock(cal_day.open_utc())
    window = BarWindow(conn, calendar, clock, ANCHOR, lookback_days=1)
    baseline = RvolBaseline.load(conn, calendar, "SPY", ANCHOR)
    fired: set = set()
    live: list = []
    while clock.current < cal_day.close_utc():
        clock.current = clock.current + timedelta(minutes=1)
        live += live_signals(window, "SPY", RULES, fired, rvol_baseline=baseline)

    assert [s.to_json() for s in live] == [s.to_json() for s in batch]


def test_unlock_filter_hides_locked_concepts(conn):
    build_orb_day(conn)
    calendar = MarketCalendar(conn)
    rules = dict(RULES)
    rules["unlocks"] = {"opening_range_breakout": 8, "trend_state": 4,
                       "vwap_reclaim": 8, "level_break": 8}
    from app.detectors.engine import unlocked_setups

    only_m4 = unlocked_setups(rules, {1, 2, 3, 4})
    assert only_m4 == {"trend_state"}
    signals = scan_day(conn, calendar, "SPY", ANCHOR, RULES, unlocked=only_m4)
    assert {s.setup_type for s in signals} == {"trend_up"}