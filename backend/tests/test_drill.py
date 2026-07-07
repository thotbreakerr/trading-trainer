"""Drill mode: discovery from cache, anti-lookahead session wiring, the
pass/trade/resolve loop, persistence, and stats (all function-level; the
endpoints run against a stub Request like every other router helper)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import sessions
from app.api import drill_api, sessions_api
from app.config import AppConfig
from app.drill import service
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, eod_clock
from app.marketday.hindsight import track_outcome
from app.models import et_clock_to_utc, et_date
from app.stores import progress
from app.stores import setups as setups_store
from tests.test_batch_golden import ANCHOR, RULES, _cd, build_orb_day

DRILL_RULES = RULES | {
    "unlocks": {
        "opening_range_breakout": 8,
        "vwap_reclaim": 8,
        "vwap_pullback": 8,
        "level_break": 8,
        "gap_fill": 8,
    },
    "grading": {"min_rr": 2.0, "min_rvol": 1.5},
}
LESSONS = [SimpleNamespace(module=8, steps=[SimpleNamespace(index=0), SimpleNamespace(index=1)])]
FORBIDDEN_KEYS = {"fired_ts", "entry", "stop", "target", "direction", "setup_type", "rr", "outcome", "signal"}


def _complete_module_8(conn) -> None:
    progress.mark_step(conn, 8, 0)
    progress.mark_step(conn, 8, 1)


def fake_request(tmp_path) -> SimpleNamespace:
    cfg = AppConfig(
        watchlist=["SPY"],
        starting_balance=30_000.0,
        intraday_leverage=4.0,
        default_risk_pct=1.0,
        backfill_days=5,
        rvol_baseline_days=3,
        poll_interval_seconds=60,
        db_path=tmp_path / "test.db",  # the conn fixture's DB
        allow_untrained_trading=False,
    )
    state = SimpleNamespace(cfg=cfg, rules=DRILL_RULES, lessons=LESSONS, provider=None)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _discover(conn, count=10):
    calendar = MarketCalendar(conn)
    return service.discover(conn, calendar, DRILL_RULES, ["SPY"], "opening_range_breakout", count)


# ------------------------------------------------------------------ discovery


def test_discovery_finds_golden_orb_instance(conn):
    build_orb_day(conn)
    instances, _ = _discover(conn)
    assert len(instances) == 1
    sig = instances[0].signal
    assert (sig.setup_type, sig.direction) == ("orb_long", "long")
    assert (sig.entry, sig.stop, sig.target) == (100.4, 99.6, 102.0)
    assert sig.ts == et_clock_to_utc(ANCHOR, "09:45")


def test_discovery_is_deterministic_for_unchanged_state(conn):
    build_orb_day(conn)
    a, _ = _discover(conn)
    b, _ = _discover(conn)
    assert [(i.signal.symbol, i.day, i.signal.setup_type) for i in a] == [
        (i.signal.symbol, i.day, i.signal.setup_type) for i in b
    ]


def test_discovery_excludes_already_drilled_identity(conn):
    build_orb_day(conn)
    (inst,), _ = _discover(conn)
    setups_store.insert_setup(
        conn, day=inst.day, signal=inst.signal, grade=None, status="fired", mode="drill"
    )
    assert _discover(conn)[0] == []
    # ...but a PRACTICE row for the same identity does not consume the drill
    conn.execute("DELETE FROM setups")
    setups_store.insert_setup(
        conn, day=inst.day, signal=inst.signal, grade=None, status="fired", mode="practice"
    )
    assert len(_discover(conn)[0]) == 1


def test_discovery_skips_incomplete_days(conn):
    build_orb_day(conn)
    # re-mark the anchor as fetched BEFORE its close -> not drillable yet
    store.mark_day_cached(conn, "SPY", ANCHOR, _cd(ANCHOR).session_close_utc() - timedelta(hours=2))
    assert _discover(conn)[0] == []


def test_informational_signals_are_not_drillable():
    assert service.concept_of("trend_up") is None
    assert service.concept_of("gap_up") is None
    assert service.concept_of("rvol_spike") is None
    assert service.concept_of("orb_short") == "opening_range_breakout"
    assert service.concept_of("level_break_pmh") == "level_break"
    assert service.concept_of("vwap_loss") == "vwap_reclaim"


# ------------------------------------------------------------------- gating


def test_gating_requires_module_eight(conn, tmp_path):
    build_orb_day(conn)
    request = fake_request(tmp_path)
    with pytest.raises(HTTPException) as e:
        drill_api.start_run(drill_api.StartRunIn(setup="opening_range_breakout"), request)
    assert e.value.status_code == 403
    assert drill_api.drill_setups(request) == {"unlocked": False, "gate_module": 8, "setups": []}
    _complete_module_8(conn)
    run = drill_api.start_run(drill_api.StartRunIn(setup="opening_range_breakout"), request)
    assert run["total"] == 1
    assert drill_api.drill_setups(request)["unlocked"] is True


# ------------------------------------------------- attempt start / anti-leak


def _start_attempt(conn, tmp_path):
    build_orb_day(conn)
    _complete_module_8(conn)
    request = fake_request(tmp_path)
    run = drill_api.start_run(drill_api.StartRunIn(setup="opening_range_breakout"), request)
    payload = drill_api.next_attempt(run["run_id"], request)
    return request, run, payload


def test_attempt_start_jitter_within_bounds(conn, tmp_path):
    request, _, payload = _start_attempt(conn, tmp_path)
    session = sessions.get_session(payload["session"]["id"])
    fire = et_clock_to_utc(ANCHOR, "09:45")
    open_utc = et_clock_to_utc(ANCHOR, "09:30")
    assert session.start_at >= open_utc
    assert session.start_at <= fire - timedelta(minutes=service.JITTER_BARS[0])
    assert session.start_at >= fire - timedelta(minutes=service.JITTER_BARS[1])
    assert session.mode == "drill" and session.sim.mode == "drill"


def test_attempt_payload_never_leaks_fire_fields(conn, tmp_path):
    _, _, payload = _start_attempt(conn, tmp_path)

    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                assert k not in FORBIDDEN_KEYS, f"{path}.{k} leaks setup data pre-resolve"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(payload)
    assert payload["done"] is False and payload["total"] == 1


def test_run_exhaustion_reports_done(conn, tmp_path):
    request, run, _ = _start_attempt(conn, tmp_path)
    assert drill_api.next_attempt(run["run_id"], request) == {"done": True}


# --------------------------------------------------------------- resolution


def test_pass_resolution_matches_hindsight_golden(conn, tmp_path):
    request, _, payload = _start_attempt(conn, tmp_path)
    result = drill_api.resolve_attempt(payload["attempt_id"], request)

    assert result["setup"]["setup_type"] == "orb_long"
    assert result["setup"]["fired_et"] == "09:45"
    assert result["user"]["took"] is False and result["user"]["grade"] is None

    # equals a direct hindsight call over the whole day's bars
    calendar = MarketCalendar(conn)
    window = BarWindow(conn, calendar, eod_clock(calendar.day(ANCHOR)), ANCHOR, lookback_days=1)
    fire = et_clock_to_utc(ANCHOR, "09:45")
    day_bars = [b for b in window.bars_1m("SPY") if et_date(b.ts) == ANCHOR and b.ts >= fire]
    direct = track_outcome(day_bars, "long", 100.4, 99.6, 102.0)
    assert result["outcome"] == {
        "outcome": direct.outcome,
        "r_multiple": direct.r_multiple,
        "exit_price": direct.exit_price,
    }
    assert direct.outcome == "target" and direct.r_multiple == 2.0

    row = setups_store.list_mode_setups(conn, "drill")[0]
    assert row["status"] == "passed" and row["taken"] == 0
    assert row["outcome"] == "target" and row["outcome_r"] == 2.0


def test_trade_resolution_persists_first_grade(conn, tmp_path):
    request, _, payload = _start_attempt(conn, tmp_path)
    session_id = payload["session"]["id"]
    session = sessions.get_session(session_id)
    calendar = MarketCalendar(conn)
    window = BarWindow(conn, calendar, session.clock, ANCHOR, lookback_days=1)
    sessions.step_session(session, window, 5)  # reveal a few bars -> last_close exists

    order = sessions_api.place_order(
        session_id,
        sessions_api.OrderIn(side="buy", qty=10, stop_price=99.6, target_price=102.0),
        request,
    )
    assert order["grade"] is not None
    first_tier = order["grade"]["tier"]

    # a second, sloppier bracket must NOT overwrite the first-grade rep
    sessions_api.place_order(
        session_id,
        sessions_api.OrderIn(side="buy", qty=1, stop_price=90.0, target_price=100.6),
        request,
    )
    assert session.drill_ctx.first_grade.tier == first_tier

    result = drill_api.resolve_attempt(payload["attempt_id"], request)
    assert result["user"]["took"] is True
    assert result["user"]["grade"]["tier"] == first_tier
    row = setups_store.list_mode_setups(conn, "drill")[0]
    assert row["taken"] == 1 and row["status"] == "acted" and row["user_grade"] == first_tier


def test_resolve_is_idempotent_and_blocks_orders(conn, tmp_path):
    request, _, payload = _start_attempt(conn, tmp_path)
    first = drill_api.resolve_attempt(payload["attempt_id"], request)
    second = drill_api.resolve_attempt(payload["attempt_id"], request)
    assert first == second
    assert len(setups_store.list_mode_setups(conn, "drill")) == 1  # one row, not two

    session = sessions.get_session(payload["session"]["id"])
    calendar = MarketCalendar(conn)
    window = BarWindow(conn, calendar, session.clock, ANCHOR, lookback_days=1)
    sessions.step_session(session, window, 5)
    with pytest.raises(HTTPException) as e:
        sessions_api.place_order(
            payload["session"]["id"],
            sessions_api.OrderIn(side="buy", qty=10, stop_price=99.6, target_price=102.0),
            request,
        )
    assert e.value.status_code == 409  # no trading after the reveal


# -------------------------------------------------------------------- stats


def test_drill_stats_derive_at_read_time(conn, tmp_path):
    request, _, payload = _start_attempt(conn, tmp_path)
    drill_api.resolve_attempt(payload["attempt_id"], request)  # one passed rep

    stats = drill_api.drill_stats(request)["setups"]
    orb = next(s for s in stats if s["key"] == "opening_range_breakout")
    assert orb["attempts"] == 1 and orb["passed"] == 1 and orb["taken"] == 0
    assert orb["passed_avg_outcome_r"] == 2.0 and orb["taken_avg_outcome_r"] is None
    assert orb["by_day"] == [{"day": ANCHOR.isoformat(), "attempts": 1, "grades": {}}]
