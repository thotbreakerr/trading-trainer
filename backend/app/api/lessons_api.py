"""Lesson endpoints (doc §7, §12): module list with lock states, step
serving (quiz answers never leak), server-validated completion in strict
step order, and lesson-mode replay sessions that allow seek."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import sessions
from app.api import deps
from app.lessons.loader import STATUS_OK, LessonModule, LessonStep
from app.marketdata.calendar import CalendarUnavailable
from app.models import et_clock_to_utc
from app.stores import progress

logger = logging.getLogger(__name__)
router = APIRouter()


def _modules(request: Request) -> list[LessonModule]:
    return request.app.state.lessons


def _find(request: Request, module_number: int) -> LessonModule:
    for mod in _modules(request):
        if mod.module == module_number:
            return mod
    raise HTTPException(status_code=404, detail=f"no module {module_number}")


def _statuses(request: Request) -> dict[int, dict]:
    """Linear unlock (doc §12): module N opens when N-1 is complete."""
    conn = deps.get_db(request)
    done = progress.completed_steps(conn)
    out: dict[int, dict] = {}
    previous_complete = True  # module 1 is always unlocked
    for mod in sorted(_modules(request), key=lambda m: m.module):
        completed = len(done.get(mod.module, set()) & {s.index for s in mod.steps})
        complete = mod.status == STATUS_OK and completed == len(mod.steps)
        if mod.status != STATUS_OK:
            status = "unavailable"
        elif complete:
            status = "complete"
        elif previous_complete:
            status = "available"
        else:
            status = "locked"
        out[mod.module] = {
            "status": status,
            "completed_steps": completed,
            "total_steps": len(mod.steps),
        }
        previous_complete = complete
    return out


def _step_json(step: LessonStep, completed: bool) -> dict:
    data = {
        "index": step.index,
        "type": step.type,
        "title": step.title,
        "body": step.body,
        "completed": completed,
    }
    if step.type == "action":
        data["pointer"] = {"target": step.pointer_target, "label": step.pointer_label}
    if step.type in ("replay", "practice"):
        data["symbol"] = step.symbol
        data["date"] = step.day.isoformat() if step.day else None
        data["pauses"] = [
            {
                "at": p["at"],
                "note": p["note"],
                # epoch so the client never does ET/DST math
                "ts": int(et_clock_to_utc(step.day, p["at"]).timestamp()),
            }
            for p in step.pauses
        ]
        data["goal"] = step.goal
    if step.type == "quiz":
        data["question"] = step.question
        # choices WITHOUT correct/explain — the server grades (doc: quiz
        # must be answered correctly to advance)
        data["choices"] = [c["text"] for c in step.choices]
    return data


@router.get("/lessons")
def list_lessons(request: Request) -> dict:
    statuses = _statuses(request)
    return {
        "modules": [
            {
                "module": mod.module,
                "title": mod.title,
                "summary": mod.summary,
                "status_reason": mod.status_reason,
                **statuses[mod.module],
            }
            for mod in _modules(request)
        ]
    }


@router.get("/lessons/{module_number}")
def get_lesson(module_number: int, request: Request) -> dict:
    mod = _find(request, module_number)
    info = _statuses(request)[mod.module]
    if info["status"] == "unavailable":
        raise HTTPException(status_code=409, detail=mod.status_reason or "module unavailable")
    if info["status"] == "locked":
        raise HTTPException(status_code=403, detail="complete the previous module first")
    done = progress.completed_steps(deps.get_db(request)).get(mod.module, set())
    return {
        "module": mod.module,
        "title": mod.title,
        "summary": mod.summary,
        "chart": (
            {"symbol": mod.chart_symbol, "date": mod.chart_day.isoformat()}
            if mod.chart_symbol and mod.chart_day
            else None
        ),
        **info,
        "steps": [_step_json(s, s.index in done) for s in mod.steps],
    }


class CompleteIn(BaseModel):
    answer: int | None = None  # quiz choice index
    grade: str | None = None  # practice grade (used from the rules phase on)


@router.post("/lessons/{module_number}/steps/{step_index}/complete")
def complete_step(
    module_number: int, step_index: int, request: Request, body: CompleteIn | None = None
) -> dict:
    mod = _find(request, module_number)
    if not (0 <= step_index < len(mod.steps)):
        raise HTTPException(status_code=404, detail="no such step")
    info = _statuses(request)[mod.module]
    if info["status"] in ("locked", "unavailable"):
        raise HTTPException(status_code=403, detail=f"module is {info['status']}")
    conn = deps.get_db(request)
    done = progress.completed_steps(conn).get(mod.module, set())
    if step_index > 0 and (step_index - 1) not in done:
        raise HTTPException(status_code=409, detail="complete the previous step first")

    step = mod.steps[step_index]
    if step.type == "quiz":
        if body is None or body.answer is None:
            raise HTTPException(status_code=400, detail="quiz needs an answer index")
        if not (0 <= body.answer < len(step.choices)):
            raise HTTPException(status_code=400, detail="answer out of range")
        choice = step.choices[body.answer]
        if not choice["correct"]:
            return {"completed": False, "correct": False, "explain": choice["explain"]}
        progress.mark_step(conn, mod.module, step_index)
        return {"completed": True, "correct": True, "explain": choice["explain"]}

    grade = body.grade if body else None
    progress.mark_step(conn, mod.module, step_index, practice_grade=grade)
    return {"completed": True}


@router.post("/lessons/{module_number}/steps/{step_index}/session")
def lesson_session(module_number: int, step_index: int, request: Request) -> dict:
    """Replay session for a Watch/Practice step — mode='lesson', which is the
    only mode allowed to seek (doc §8)."""
    mod = _find(request, module_number)
    if not (0 <= step_index < len(mod.steps)):
        raise HTTPException(status_code=404, detail="no such step")
    step = mod.steps[step_index]
    if step.symbol is None or step.day is None:
        raise HTTPException(status_code=400, detail="step has no replay day")
    fetcher = deps.get_fetcher(request)
    if fetcher is not None:
        try:
            fetcher.ensure_day(step.symbol, step.day)
        except Exception as e:
            logger.warning("lesson day fetch failed %s %s: %s", step.symbol, step.day, e)
    try:
        session = sessions.create_session(
            deps.get_calendar(request),
            [step.symbol],
            step.day,
            lookback_days=3,
            start=step.start,
            mode="lesson",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CalendarUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "id": session.id,
        "mode": session.mode,
        "symbols": session.symbols,
        "day": session.day.isoformat(),
        "clock": int(session.clock.current.timestamp()),
        "done": session.done,
        "start_at": int(session.start_at.timestamp()),
        "end_at": int(session.end_at.timestamp()),
    }
