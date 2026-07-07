"""Step deltas (doc §8): the trailing slice a step returns must merge onto the
previous full payload into EXACTLY what a fresh bars fetch would return.

Contract doc: app/api/chart_payload.py. Frontend mirror of _merge():
frontend/src/lib/mergeStepDelta.ts (same splice rule, same fixtures shape).
"""
from __future__ import annotations

from datetime import date
from itertools import cycle

import pytest

from app import sessions
from app.api.chart_payload import chart_series, series_json, slice_step_delta
from app.marketdata.aggregate import TF_MINUTES, bucket_start
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, eod_clock
from app.models import CalendarDay, et_date
from tests.conftest import seed_days

ANCHOR = date(2026, 6, 17)
RVOL_DAYS = 2  # the fixture calendar can't serve the default 20
TFS = ["1m", "5m", "15m", "1h"]


def _cd(d: date, close: str = "16:00") -> CalendarDay:
    return CalendarDay(d, "09:30", close, "04:00", "20:00")


def _days() -> list[CalendarDay]:
    return [_cd(date(2026, 6, 15)), _cd(date(2026, 6, 16)), _cd(ANCHOR)]


def make(conn, start: str = "open"):
    seed_days(conn, "SPY", _days())
    calendar = MarketCalendar(conn)
    session = sessions.create_session(calendar, ["SPY"], ANCHOR, lookback_days=2, start=start)
    window = BarWindow(conn, calendar, session.clock, ANCHOR, lookback_days=2)
    return session, window


def _payload(window: BarWindow, tf: str) -> dict:
    return series_json(chart_series(window, "SPY", tf, rvol_baseline_days=RVOL_DAYS))


def _splice(prev: list[dict], tail: list[dict]) -> list[dict]:
    if not tail:
        return prev
    cut = tail[0]["t"]
    return [x for x in prev if x["t"] < cut] + tail


def _merge(prev: dict, delta: dict) -> dict:
    """Reference merge — mirrors frontend/src/lib/mergeStepDelta.ts."""
    return {
        "bars": _splice(prev["bars"], delta["bars"]),
        "overlays": {k: _splice(prev["overlays"][k], delta["overlays"][k]) for k in prev["overlays"]},
        "rvol": delta["rvol"],
    }


def _run_invariant(conn, tf: str, steps, start: str, max_iters: int | None = None) -> int:
    """Step through the session asserting merge(prev, delta) == fresh fetch."""
    session, window = make(conn, start=start)
    day_map = {d.day: d for d in window.days}
    merged = _payload(window, tf)
    iters = 0
    step_iter = iter(steps)
    while not session.done:
        result = sessions.step_session(session, window, next(step_iter))
        delta = series_json(
            slice_step_delta(
                chart_series(window, "SPY", tf, rvol_baseline_days=RVOL_DAYS),
                result.new_bars.get("SPY", []),
                tf,
                day_map,
            )
        )
        merged = _merge(merged, delta)
        assert merged == _payload(window, tf), f"divergence at clock={result.clock} tf={tf}"
        iters += 1
        assert iters < 2000, "runaway session"
        if max_iters is not None and iters >= max_iters:
            break
    return iters


@pytest.mark.parametrize("tf", TFS)
def test_merge_equals_fresh_fetch_full_day_mixed_steps(conn, tf):
    """Whole extended session (pre 04:00 anchor -> RTH -> post) with every
    planned step size, crossing all segment re-anchors along the way."""
    iters = _run_invariant(conn, tf, cycle([1, 2, 5, 7, 60]), start="session_open")
    assert iters > 10  # sanity: the day actually played out


@pytest.mark.parametrize("tf", TFS)
def test_merge_equals_fresh_fetch_dense_open(conn, tf):
    """One-bar steps through early RTH — maximum partial-bucket churn."""
    _run_invariant(conn, tf, cycle([1]), start="open", max_iters=45)


def test_delta_crosses_session_open_boundary(conn):
    """Single steps across the pre->RTH re-anchor at 09:30 (15m buckets)."""
    session, window = make(conn, start="session_open")
    day_map = {d.day: d for d in window.days}
    tf = "15m"
    merged = _payload(window, tf)
    for n in [60, 60, 60, 60, 60, 25] + [1] * 10:  # land at 09:25, walk across
        result = sessions.step_session(session, window, n)
        delta = series_json(
            slice_step_delta(
                chart_series(window, "SPY", tf, rvol_baseline_days=RVOL_DAYS),
                result.new_bars.get("SPY", []),
                tf,
                day_map,
            )
        )
        merged = _merge(merged, delta)
        assert merged == _payload(window, tf)


def test_delta_after_done_is_empty_but_carries_rvol(conn):
    session, window = make(conn, start="open")
    day_map = {d.day: d for d in window.days}
    while not session.done:
        sessions.step_session(session, window, 60)
    before = _payload(window, "5m")
    result = sessions.step_session(session, window, 60)  # step past done
    assert result.new_bars["SPY"] == []
    sliced = slice_step_delta(
        chart_series(window, "SPY", "5m", rvol_baseline_days=RVOL_DAYS),
        result.new_bars["SPY"],
        "5m",
        day_map,
    )
    assert sliced.bars == [] and sliced.vwap == [] and sliced.ema9 == []
    assert _merge(before, series_json(sliced)) == before


def test_partial_bucket_upsert_keeps_open_updates_hlcv(conn):
    """The trailing 5m bucket re-sent by each step keeps its open while
    high/low/close/volume accumulate — upsert, not append (doc §8)."""
    session, window = make(conn, start="open")
    day_map = {d.day: d for d in window.days}

    def delta_bars():
        result = sessions.step_session(session, window, 1)
        return series_json(
            slice_step_delta(
                chart_series(window, "SPY", "5m", rvol_baseline_days=RVOL_DAYS),
                result.new_bars.get("SPY", []),
                "5m",
                day_map,
            )
        )["bars"]

    first = delta_bars()  # reveals 09:30 -> bucket [09:30) created
    second = delta_bars()  # reveals 09:31 -> same bucket, updated
    assert [b["t"] for b in first] == [b["t"] for b in second]
    assert first[0]["o"] == second[0]["o"]  # open fixed
    assert second[0]["c"] != first[0]["c"]  # close moved (fixture ramps +0.01/min)
    assert second[0]["v"] > first[0]["v"]  # volume accumulated
    assert second[0]["h"] >= first[0]["h"]


@pytest.mark.parametrize("tf", ["5m", "15m", "1h"])
def test_bucket_start_matches_aggregate_buckets(conn, tf):
    """bucket_start() must agree with aggregate_bars() bucketing everywhere —
    including the half-day post anchor (Thanksgiving Friday, 13:00 close)."""
    days = [_cd(date(2026, 11, 25)), _cd(date(2026, 11, 27), close="13:00")]
    seed_days(conn, "SPY", days)
    calendar = MarketCalendar(conn)
    for cd in days:
        window = BarWindow(conn, calendar, eod_clock(cd), cd.day, lookback_days=0)
        ones = [b for b in window.bars_1m("SPY") if et_date(b.ts) == cd.day]
        agg_ts = {b.ts for b in window.bars("SPY", tf) if et_date(b.ts) == cd.day}
        assert {bucket_start(b, cd, TF_MINUTES[tf]) for b in ones} == agg_ts
