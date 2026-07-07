"""Drill endpoints: pick an unlocked concept, mine cached history for
instances, replay each one blind (jittered start, no setup fields in any
payload), act or pass, then resolve for the full reveal. Router stays thin
(deps.py convention) — logic lives in app/drill/service.py."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import sessions
from app.api import deps
from app.api.sessions_api import _info
from app.drill import runs as drill_runs
from app.drill import service
from app.sim.engine import SimEngine

logger = logging.getLogger(__name__)
router = APIRouter()


def _empty_stats(key: str) -> dict:
    return {
        "key": key,
        "label": service.LABELS[key],
        "attempts": 0,
        "taken": 0,
        "passed": 0,
        "grade_distribution": {},
        "taken_avg_outcome_r": None,
        "passed_avg_outcome_r": None,
        "by_day": [],
    }


@router.get("/drill/setups")
def drill_setups(request: Request) -> dict:
    conn = deps.get_db(request)
    unlocked = service.unlocked_drillable(conn, request.app.state.lessons, request.app.state.rules)
    stats = {s["key"]: s for s in service.drill_stats(conn)}
    return {
        "unlocked": bool(unlocked),
        "gate_module": service.GATE_MODULE,
        "setups": [stats.get(key, _empty_stats(key)) for key in sorted(unlocked)],
    }


class StartRunIn(BaseModel):
    setup: str
    count: int = Field(default=10, ge=1, le=25)


@router.post("/drill/runs")
def start_run(body: StartRunIn, request: Request) -> dict:
    if body.setup not in service.DRILLABLE:
        raise HTTPException(status_code=404, detail=f"unknown drill setup {body.setup!r}")
    conn = deps.get_db(request)
    if body.setup not in service.unlocked_drillable(
        conn, request.app.state.lessons, request.app.state.rules
    ):
        raise HTTPException(
            status_code=403, detail=f"locked — complete module {service.GATE_MODULE} first"
        )
    cfg = deps.get_cfg(request)
    instances, rng = service.discover(
        conn, deps.get_calendar(request), request.app.state.rules, cfg.watchlist, body.setup, body.count
    )
    if not instances:
        return {"run_id": None, "setup": body.setup, "total": 0}
    run = drill_runs.put_run(body.setup, instances, rng)
    return {"run_id": run.id, "setup": run.setup, "total": len(run.instances)}


@router.post("/drill/runs/{run_id}/next")
def next_attempt(run_id: str, request: Request) -> dict:
    try:
        run = drill_runs.get_run(run_id)
    except drill_runs.RunNotFound:
        raise HTTPException(status_code=404, detail="no such drill run")
    idx = drill_runs.take_next(run)
    # GC the previous attempt's session — one live drill session at a time
    if idx is None or idx > 0:
        prev = run.instances[(idx - 1) if idx is not None else len(run.instances) - 1]
        if prev.session_id:
            sessions.delete_session(prev.session_id)
    if idx is None:
        return {"done": True}
    inst = run.instances[idx]
    cfg = deps.get_cfg(request)
    calendar = deps.get_calendar(request)
    cal_day = calendar.day(inst.day)
    if cal_day is None:
        raise HTTPException(status_code=409, detail=f"{inst.day} vanished from the calendar cache")
    attempt_id = drill_runs.register_attempt(run, idx)
    session = sessions.create_session(
        calendar,
        [inst.signal.symbol],
        inst.day,
        # one prior day: exactly what grading needs (levels/prior close), and
        # drillable days near the cache edge stay drillable
        lookback_days=1,
        start_at=service.jitter_start(cal_day, inst.signal, run.rng),
        mode="drill",
        sim=SimEngine(cfg.starting_balance, cfg.intraday_leverage, mode="drill"),
        drill_ctx=sessions.DrillCtx(attempt_id=attempt_id),
    )
    inst.session_id = session.id
    # ANTI-LOOKAHEAD: nothing here names the setup, direction, bracket, or
    # fire time — start_at is jittered 8-20 bars ahead of the fire.
    return {
        "done": False,
        "attempt_id": attempt_id,
        "idx": idx,
        "total": len(run.instances),
        "session": _info(session),
    }


@router.post("/drill/attempts/{attempt_id}/resolve")
def resolve_attempt(attempt_id: str, request: Request) -> dict:
    try:
        run, idx, inst = drill_runs.get_attempt(attempt_id)
    except drill_runs.AttemptNotFound:
        raise HTTPException(status_code=404, detail="no such drill attempt")
    session = None
    if inst.result is None:
        if inst.session_id is None:
            raise HTTPException(status_code=409, detail="attempt has no session")
        try:
            session = sessions.get_session(inst.session_id)
        except sessions.SessionNotFound:
            raise HTTPException(
                status_code=409, detail="session is gone — move on to the next instance"
            )
    try:
        result = service.resolve(
            deps.get_db(request),
            deps.get_calendar(request),
            request.app.state.rules,
            run,
            inst,
            session,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"attempt_id": attempt_id, "idx": idx, "total": len(run.instances), **result}


@router.get("/drill/stats")
def drill_stats(request: Request) -> dict:
    return {"setups": service.drill_stats(deps.get_db(request))}
