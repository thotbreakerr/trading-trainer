"""Journal endpoints (doc §15.3): the trades table with replay jump-back
payloads, and the trajectory dashboard numbers — all derived at read time."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api import deps
from app.journal import reviews, stats
from app.models import ET, from_db_ts

router = APIRouter()


def _trade_json(row: sqlite3.Row) -> dict:
    item = dict(row)
    entry_ts = from_db_ts(item["entry_ts"])
    item["entry_et"] = entry_ts.astimezone(ET).strftime("%Y-%m-%d %H:%M")
    item["replay"] = {
        "symbol": item["symbol"],
        "day": item["day"],
        "start_at": int(entry_ts.timestamp()) - 300,  # open five minutes before
    }
    item["review"] = reviews.review_json(row)
    for key in list(item):
        if key.startswith("review_"):
            del item[key]
    return item


TRADE_MODES = ("practice", "marketday", "drill", "scenario")
TRADE_SELECT = (
    "SELECT t.*, s.setup_type, "
    "r.thesis AS review_thesis, r.notes AS review_notes, r.confidence AS review_confidence, "
    "r.emotion AS review_emotion, r.mistakes AS review_mistakes, r.tags AS review_tags, "
    "r.reviewed AS review_reviewed, r.updated_at AS review_updated_at "
    "FROM trades t LEFT JOIN setups s ON s.id = t.setup_id "
    "LEFT JOIN trade_reviews r ON r.trade_id = t.id"
)


@router.get("/journal/trades")
def journal_trades(
    request: Request,
    mode: str | None = None,
    symbol: str | None = None,
    grade: str | None = None,
    setup: str | None = None,
    tag: str | None = None,
    reviewed: bool | None = None,
) -> dict:
    conn = deps.get_db(request)
    sql = TRADE_SELECT
    where: list[str] = []
    args: list = []
    if mode in TRADE_MODES:
        where.append("t.mode = ?")
        args.append(mode)
    if symbol:
        where.append("t.symbol = ?")
        args.append(symbol.upper())
    if grade:
        where.append("t.grade = ?")
        args.append(grade)
    if setup:
        where.append("s.setup_type LIKE ?")
        args.append(f"%{setup}%")
    if reviewed is not None:
        where.append("COALESCE(r.reviewed, 0) = ?")
        args.append(int(reviewed))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.day DESC, t.entry_ts DESC LIMIT 500"
    rows = conn.execute(sql, args).fetchall()
    items = [_trade_json(r) for r in rows]
    if tag:
        wanted = tag.strip().lower()
        items = [item for item in items if wanted in item["review"]["tags"]]
    return {"trades": items}


@router.get("/journal/trades/{trade_id}")
def journal_trade(trade_id: int, request: Request) -> dict:
    row = deps.get_db(request).execute(TRADE_SELECT + " WHERE t.id = ?", (trade_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such trade")
    item = _trade_json(row)
    item["metrics"] = reviews.execution_metrics(deps.get_db(request), row)
    return item


class ReviewIn(BaseModel):
    thesis: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=10000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    emotion: str = Field(default="", max_length=100)
    mistakes: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    reviewed: bool = False


@router.patch("/journal/trades/{trade_id}/review")
def update_trade_review(trade_id: int, body: ReviewIn, request: Request) -> dict:
    try:
        review = reviews.upsert_review(deps.get_db(request), trade_id, body.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="no such trade")
    return {"trade_id": trade_id, "review": review}


@router.get("/journal/stats")
def journal_stats(request: Request, mode: str | None = None) -> dict:
    conn = deps.get_db(request)
    return stats.trajectory(conn, mode if mode in TRADE_MODES else None)
