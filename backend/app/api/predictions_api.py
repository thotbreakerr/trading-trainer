"""Pre-market planning predictions."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api import deps
from app.models import ET, utcnow
from app.predictions import service

router = APIRouter()


class PredictionIn(BaseModel):
    day: date
    symbol: str = Field(min_length=1, max_length=10)
    direction: str = Field(pattern="^(bullish|bearish|neutral)$")
    key_level: float | None = Field(default=None, gt=0)
    setup: str = Field(default="", max_length=100)
    invalidation: str = Field(default="", max_length=500)
    confidence: int = Field(ge=1, le=5)


@router.get("/briefing/predictions")
def predictions(request: Request, day: date | None = None) -> dict:
    chosen = day or utcnow().astimezone(ET).date()
    return service.list_day(deps.get_db(request), deps.get_calendar(request), chosen)


@router.post("/briefing/predictions")
def save_prediction(body: PredictionIn, request: Request) -> dict:
    try:
        return service.save(
            deps.get_db(request), deps.get_calendar(request), body.day,
            body.symbol.upper(), body.model_dump(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
