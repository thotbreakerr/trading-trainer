"""Setups ledger CRUD (doc §14): every fired setup with its grade, checklist,
lifecycle status, the user's decision, and the hindsight outcome."""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from app.models import from_db_ts, to_db_ts


def insert_setup(
    conn: sqlite3.Connection,
    *,
    day: date,
    signal,
    grade,
    status: str,
    mode: str,
    note: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO setups (symbol, day, fired_ts, setup_type, direction, entry,"
        " stop, target, rr, grade, checklist, status, mode, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            signal.symbol,
            day.isoformat(),
            to_db_ts(signal.ts),
            signal.setup_type,
            signal.direction,
            signal.entry,
            signal.stop,
            signal.target,
            signal.rr,
            grade.tier if grade else None,
            json.dumps(grade.to_json()["checklist"]) if grade else None,
            status,
            mode,
            note,
        ),
    )
    return int(cur.lastrowid)


def update_status(
    conn: sqlite3.Connection, setup_id: int, status: str, note: str | None = None
) -> None:
    if note is not None:
        conn.execute(
            "UPDATE setups SET status = ?, note = ? WHERE id = ?", (status, note, setup_id)
        )
    else:
        conn.execute("UPDATE setups SET status = ? WHERE id = ?", (status, setup_id))


def record_outcome(
    conn: sqlite3.Connection, setup_id: int, outcome: str, outcome_r: float | None
) -> None:
    conn.execute(
        "UPDATE setups SET outcome = ?, outcome_r = ? WHERE id = ?",
        (outcome, outcome_r, setup_id),
    )


def record_user_action(
    conn: sqlite3.Connection, setup_id: int, ts, user_grade, user_checklist_json: str
) -> None:
    conn.execute(
        "UPDATE setups SET taken = 1, status = 'acted', user_action_ts = ?,"
        " user_grade = ?, user_checklist = ? WHERE id = ?",
        (to_db_ts(ts), user_grade, user_checklist_json, setup_id),
    )


def list_setups(conn: sqlite3.Connection, day: date, mode: str | None = None) -> list[dict]:
    sql = "SELECT * FROM setups WHERE day = ?"
    args: list = [day.isoformat()]
    if mode:
        sql += " AND mode = ?"
        args.append(mode)
    sql += " ORDER BY fired_ts"
    out = []
    for row in conn.execute(sql, args):
        item = dict(row)
        item["checklist"] = json.loads(item["checklist"]) if item["checklist"] else []
        item["user_checklist"] = (
            json.loads(item["user_checklist"]) if item["user_checklist"] else None
        )
        item["fired_et"] = from_db_ts(item["fired_ts"]).astimezone().strftime("%H:%M")
        out.append(item)
    return out


def list_mode_setups(conn: sqlite3.Connection, mode: str) -> list[dict]:
    """Day-agnostic variant of list_setups — drill stats aggregate over it."""
    out = []
    for row in conn.execute("SELECT * FROM setups WHERE mode = ? ORDER BY day, fired_ts", (mode,)):
        item = dict(row)
        item["checklist"] = json.loads(item["checklist"]) if item["checklist"] else []
        item["user_checklist"] = (
            json.loads(item["user_checklist"]) if item["user_checklist"] else None
        )
        out.append(item)
    return out


def get_setup(conn: sqlite3.Connection, setup_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM setups WHERE id = ?", (setup_id,)).fetchone()
