"""Journal endpoints (doc §15.3): the trades table with replay jump-back
payloads, and the trajectory dashboard numbers — all derived at read time."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request

from app.api import deps
from app.journal import stats
from app.models import ET, from_db_ts

router = APIRouter()


def _trade_json(row: sqlite3.Row) -> dict:
    item = dict(row)
    entry_ts = from_db_ts(item["entry_ts"])
    item["entry_et"] = entry_ts.astimezone(ET).strftime("%Y-%m-%d %H:%M")
    item["review"] = {
        "symbol": item["symbol"],
        "day": item["day"],
        "start_at": int(entry_ts.timestamp()) - 300,  # open five minutes before
    }
    return item


@router.get("/journal/trades")
def journal_trades(request: Request, mode: str | None = None) -> dict:
    conn = deps.get_db(request)
    sql = "SELECT * FROM trades"
    args: list = []
    if mode in ("practice", "marketday", "drill"):
        sql += " WHERE mode = ?"
        args.append(mode)
    sql += " ORDER BY day DESC, entry_ts DESC LIMIT 500"
    rows = conn.execute(sql, args).fetchall()
    return {"trades": [_trade_json(r) for r in rows]}


@router.get("/journal/stats")
def journal_stats(request: Request, mode: str | None = None) -> dict:
    conn = deps.get_db(request)
    return stats.trajectory(conn, mode if mode in ("practice", "marketday", "drill") else None)
