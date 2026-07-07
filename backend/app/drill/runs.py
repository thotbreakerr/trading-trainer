"""In-memory drill-run registry (mirrors sessions._SESSIONS): signal data
stays server-side so nothing about the fire moment can leak to the client
before resolve. Single-user app: creating a run replaces the previous one;
runs die with the process, same documented tradeoff as replay sessions."""
from __future__ import annotations

import random
import threading
import uuid
from dataclasses import dataclass
from datetime import date

from app.detectors.types import Signal


class RunNotFound(KeyError):
    pass


class AttemptNotFound(KeyError):
    pass


@dataclass
class DrillInstance:
    signal: Signal
    day: date
    attempt_id: str | None = None
    session_id: str | None = None
    resolved: bool = False
    result: dict | None = None  # resolve() caches here -> idempotent


@dataclass
class DrillRun:
    id: str
    setup: str  # concept unlock key, e.g. 'opening_range_breakout'
    instances: list[DrillInstance]
    rng: random.Random
    next_idx: int = 0


_RUNS: dict[str, DrillRun] = {}
_ATTEMPTS: dict[str, tuple[str, int]] = {}  # attempt_id -> (run_id, instance idx)
_LOCK = threading.Lock()


def put_run(setup: str, instances: list[DrillInstance], rng: random.Random) -> DrillRun:
    run = DrillRun(id=uuid.uuid4().hex[:8], setup=setup, instances=instances, rng=rng)
    with _LOCK:
        _RUNS.clear()
        _ATTEMPTS.clear()
        _RUNS[run.id] = run
    return run


def get_run(run_id: str) -> DrillRun:
    with _LOCK:
        run = _RUNS.get(run_id)
    if run is None:
        raise RunNotFound(run_id)
    return run


def take_next(run: DrillRun) -> int | None:
    """Claim the next instance index (None when exhausted)."""
    with _LOCK:
        if run.next_idx >= len(run.instances):
            return None
        idx = run.next_idx
        run.next_idx += 1
        return idx


def register_attempt(run: DrillRun, idx: int) -> str:
    attempt_id = uuid.uuid4().hex[:12]
    run.instances[idx].attempt_id = attempt_id
    with _LOCK:
        _ATTEMPTS[attempt_id] = (run.id, idx)
    return attempt_id


def get_attempt(attempt_id: str) -> tuple[DrillRun, int, DrillInstance]:
    with _LOCK:
        ref = _ATTEMPTS.get(attempt_id)
    if ref is None:
        raise AttemptNotFound(attempt_id)
    run = get_run(ref[0])
    return run, ref[1], run.instances[ref[1]]
