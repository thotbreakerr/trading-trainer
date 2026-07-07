"""Drill mode: deliberate-practice reps of one setup concept mined from
cached history. Composes existing engines — batch detectors (discovery),
replay sessions (the rep), grader (the decision), hindsight (the reveal).

Design rules:
- Discovery never touches the provider: complete cached days only.
- Anti-lookahead: signal data lives in the run registry; before resolve the
  client sees only symbol/day/session bounds, with a randomized 8-20 bar
  lead before the fire so the moment can't be counted out.
- Resolution is computed AT reveal time, never precomputed into a response.
- Persistence reuses the setups ledger with mode='drill'; stats derive at
  read time (project convention: never store derivables).
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, datetime, timedelta

from app.detectors.engine import build_snapshot, scan_day, unlocked_setups
from app.detectors.types import Signal
from app.drill.runs import DrillInstance, DrillRun
from app.grading.grader import grade_signal
from app.marketdata import store
from app.marketdata.calendar import CalendarUnavailable, MarketCalendar
from app.marketdata.window import BarWindow, FixedClock, eod_clock
from app.marketday.hindsight import track_outcome
from app.models import ET, CalendarDay, et_date, to_db_ts
from app.stores import progress
from app.stores import setups as setups_store

# concept unlock key -> setup_type prefixes it emits (tradeable concepts only;
# info signals like gap context / trend state / rvol spike aren't drillable)
DRILLABLE: dict[str, tuple[str, ...]] = {
    "opening_range_breakout": ("orb_",),
    "vwap_reclaim": ("vwap_reclaim", "vwap_loss"),
    "vwap_pullback": ("vwap_pullback",),
    "level_break": ("level_break_",),
    "gap_fill": ("gap_fill",),
}
LABELS = {
    "opening_range_breakout": "Opening range breakout",
    "vwap_reclaim": "VWAP reclaim",
    "vwap_pullback": "VWAP pullback",
    "level_break": "Key-level break",
    "gap_fill": "Gap fill",
}
GATE_MODULE = 8  # where the drillable concepts unlock (rules_config unlocks)
MAX_SCAN_PAIRS = 60  # discovery cap per request — rare setups can't hang a click
JITTER_BARS = (8, 20)  # randomized lead before the fire


def concept_of(setup_type: str) -> str | None:
    for concept, prefixes in DRILLABLE.items():
        if any(setup_type.startswith(p) for p in prefixes):
            return concept
    return None


def completed_modules(conn: sqlite3.Connection, lessons) -> set[int]:
    """Same completeness rule as MarketDayPoller._unlocked."""
    done = progress.completed_steps(conn)
    return {
        m.module
        for m in lessons
        if m.steps and done.get(m.module, set()) >= {s.index for s in m.steps}
    }


def unlocked_drillable(conn: sqlite3.Connection, lessons, rules_cfg: dict) -> set[str]:
    return unlocked_setups(rules_cfg, completed_modules(conn, lessons)) & set(DRILLABLE)


def _attempts_for(conn: sqlite3.Connection, setup: str) -> int:
    prefixes = DRILLABLE[setup]
    rows = conn.execute("SELECT setup_type FROM setups WHERE mode = 'drill'")
    return sum(1 for r in rows if any(r["setup_type"].startswith(p) for p in prefixes))


def _drilled_identities(conn: sqlite3.Connection) -> set[tuple[str, str, str, str]]:
    rows = conn.execute("SELECT symbol, day, setup_type, direction FROM setups WHERE mode = 'drill'")
    return {(r["symbol"], r["day"], r["setup_type"], r["direction"]) for r in rows}


def discover(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    rules_cfg: dict,
    watchlist: list[str],
    setup: str,
    count: int,
) -> tuple[list[DrillInstance], random.Random]:
    """Sample cached (symbol, day) pairs, lazily scan them for the concept's
    signals, early-stop at `count`. Deterministic for a given DB state: the
    seed folds in how many reps you've already done, so re-requesting without
    drilling repeats the queue while completed reps rotate future runs."""
    prefixes = DRILLABLE[setup]
    rng = random.Random(f"{setup}:{_attempts_for(conn, setup)}")
    candidates: list[tuple[str, date]] = []
    for symbol in watchlist:
        for day, fetched_at in store.list_cached_days(conn, symbol):
            cal = calendar.day(day)
            if cal is None:
                continue
            if fetched_at <= cal.session_close_utc():
                continue  # incomplete day — resolution needs the full session
            candidates.append((symbol, day))
    rng.shuffle(candidates)
    drilled = _drilled_identities(conn)
    out: list[DrillInstance] = []
    for symbol, day in candidates[:MAX_SCAN_PAIRS]:
        try:
            signals = scan_day(conn, calendar, symbol, day, rules_cfg, unlocked={setup})
        except (ValueError, CalendarUnavailable):
            continue  # e.g. the oldest cached day has no lookback behind it
        for sig in signals:
            if not any(sig.setup_type.startswith(p) for p in prefixes):
                continue
            if sig.entry is None or sig.stop is None or sig.target is None:
                continue  # nothing to bracket = nothing to drill
            if (sig.symbol, day.isoformat(), sig.setup_type, sig.direction) in drilled:
                continue  # already repped — fresh instances only
            out.append(DrillInstance(signal=sig, day=day))
            if len(out) >= count:
                return out, rng
    return out, rng


def jitter_start(cal_day: CalendarDay, signal: Signal, rng: random.Random) -> datetime:
    lead = rng.randint(*JITTER_BARS)
    return max(cal_day.open_utc(), signal.ts - timedelta(minutes=lead))


def _took_and_grade(session) -> tuple[bool, object | None, datetime | None]:
    """Server-derived: the client never claims whether it traded."""
    if session is None:
        return False, None, None
    ctx = session.drill_ctx
    first_grade = ctx.first_grade if ctx else None
    first_ts = ctx.first_grade_ts if ctx else None
    sim = session.sim
    placed = sim is not None and (bool(sim.orders) or bool(sim.trades))
    return (first_grade is not None or placed), first_grade, first_ts


def resolve(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    rules_cfg: dict,
    run: DrillRun,
    inst: DrillInstance,
    session,
) -> dict:
    """Reveal + persist exactly once (idempotent via the instance cache).
    Resolving before the fire is a pass-with-spoiler: the attempt is consumed
    and further orders are blocked, so it grants no grading advantage."""
    if inst.result is not None:
        return inst.result
    sig = inst.signal
    cal_day = calendar.day(inst.day)
    if cal_day is None:  # cache vanished mid-run — treat as unresolvable
        raise ValueError(f"{inst.day} is no longer a cached trading day")

    window = BarWindow(conn, calendar, eod_clock(cal_day), inst.day, lookback_days=1)
    day_bars = [b for b in window.bars_1m(sig.symbol) if et_date(b.ts) == inst.day]
    outcome = track_outcome(
        [b for b in day_bars if b.ts >= sig.ts], sig.direction, sig.entry, sig.stop, sig.target
    )
    # coach grade AT FIRE TIME (clock clipped to the fire bar's completion) —
    # more honest than grading against the end-of-day snapshot
    fire_window = BarWindow(
        conn, calendar, FixedClock(sig.ts + timedelta(seconds=60)), inst.day, lookback_days=1
    )
    coach = grade_signal(sig, build_snapshot(fire_window, sig.symbol), rules_cfg.get("grading", {}))

    took, first_grade, first_ts = _took_and_grade(session)
    setup_id = setups_store.insert_setup(
        conn, day=inst.day, signal=sig, grade=coach, status="fired", mode="drill"
    )
    setups_store.record_outcome(conn, setup_id, outcome.outcome, outcome.r_multiple)
    if took:
        tier = getattr(first_grade, "tier", None)
        checklist = json.dumps(first_grade.to_json()["checklist"]) if first_grade else "[]"
        setups_store.record_user_action(
            conn, setup_id, first_ts or window.clock.now(), tier, checklist
        )
    else:
        setups_store.update_status(conn, setup_id, "passed")

    trade = None
    if session is not None and session.sim is not None and session.sim.trades:
        t = session.sim.trades[-1]
        trade = {
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "r_multiple": t.r_multiple,
        }
    result = {
        "setup": {
            "symbol": sig.symbol,
            "day": inst.day.isoformat(),
            "setup_type": sig.setup_type,
            "direction": sig.direction,
            "fired_ts": to_db_ts(sig.ts),
            "fired_et": sig.ts.astimezone(ET).strftime("%H:%M"),
            "entry": sig.entry,
            "stop": sig.stop,
            "target": sig.target,
            "rr": sig.rr,
            "coach_grade": coach.to_json() if coach else None,
        },
        "outcome": {
            "outcome": outcome.outcome,
            "r_multiple": outcome.r_multiple,
            "exit_price": outcome.exit_price,
        },
        "user": {
            "took": took,
            "grade": first_grade.to_json() if first_grade else None,
            "trade": trade,
        },
    }
    inst.result = result
    inst.resolved = True
    if session is not None and session.drill_ctx is not None:
        session.drill_ctx.resolved = True
    return result


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def drill_stats(conn: sqlite3.Connection) -> list[dict]:
    """Per-concept aggregates over setups WHERE mode='drill' — derived at
    read time, nothing stored."""
    per: dict[str, dict] = {}
    taken_r: dict[str, list[float]] = {}
    passed_r: dict[str, list[float]] = {}
    by_day: dict[str, dict[str, dict]] = {}
    for row in setups_store.list_mode_setups(conn, "drill"):
        concept = concept_of(row["setup_type"])
        if concept is None:
            continue
        s = per.setdefault(
            concept,
            {
                "key": concept,
                "label": LABELS[concept],
                "attempts": 0,
                "taken": 0,
                "passed": 0,
                "grade_distribution": {},
            },
        )
        s["attempts"] += 1
        if row["taken"]:
            s["taken"] += 1
            if row["user_grade"]:
                dist = s["grade_distribution"]
                dist[row["user_grade"]] = dist.get(row["user_grade"], 0) + 1
            if row["outcome_r"] is not None:
                taken_r.setdefault(concept, []).append(row["outcome_r"])
        else:
            s["passed"] += 1
            if row["outcome_r"] is not None:
                passed_r.setdefault(concept, []).append(row["outcome_r"])
        day_slot = by_day.setdefault(concept, {}).setdefault(
            row["day"], {"day": row["day"], "attempts": 0, "grades": {}}
        )
        day_slot["attempts"] += 1
        if row["taken"] and row["user_grade"]:
            day_slot["grades"][row["user_grade"]] = day_slot["grades"].get(row["user_grade"], 0) + 1
    out = []
    for concept, s in per.items():
        s["taken_avg_outcome_r"] = _avg(taken_r.get(concept, []))
        s["passed_avg_outcome_r"] = _avg(passed_r.get(concept, []))
        s["by_day"] = sorted(by_day.get(concept, {}).values(), key=lambda d: d["day"])
        out.append(s)
    return sorted(out, key=lambda s: s["key"])
