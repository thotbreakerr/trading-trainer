"""Adaptive daily workout endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request

from app.api import deps
from app.models import ET, utcnow
from app.workouts import service

router = APIRouter()


@router.post("/workouts/daily")
def daily_workout(request: Request, day: date | None = None) -> dict:
    chosen = day or utcnow().astimezone(ET).date()
    return service.daily_plan(
        deps.get_db(request), request.app.state.lessons, request.app.state.rules, chosen
    )


@router.post("/workouts/{run_id}/items/{item_id}/complete")
def complete_workout_item(run_id: int, item_id: int, request: Request) -> dict:
    try:
        return service.complete_item(deps.get_db(request), run_id, item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such workout item")


@router.get("/workouts/history")
def workout_history(request: Request) -> dict:
    rows = deps.get_db(request).execute(
        "SELECT w.*, COUNT(i.id) AS items, SUM(i.status = 'complete') AS completed_items "
        "FROM workout_runs w LEFT JOIN workout_items i ON i.run_id = w.id "
        "GROUP BY w.id ORDER BY w.day DESC LIMIT 30"
    ).fetchall()
    return {"runs": [dict(row) for row in rows]}
