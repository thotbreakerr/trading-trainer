"""Curriculum progress CRUD (doc §12): step completions + practice grades.
Unlock logic stays in the API layer — this is storage only."""
from __future__ import annotations

import sqlite3

from app.models import to_db_ts, utcnow


def mark_step(
    conn: sqlite3.Connection,
    module: int,
    step: int,
    practice_grade: str | None = None,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO progress (module, step, completed_at, practice_grade)"
        " VALUES (?, ?, ?, ?)",
        (module, step, to_db_ts(utcnow()), practice_grade),
    )


def completed_steps(conn: sqlite3.Connection) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for row in conn.execute("SELECT module, step FROM progress"):
        out.setdefault(row["module"], set()).add(row["step"])
    return out


def best_practice_grade(conn: sqlite3.Connection, module: int, step: int) -> str | None:
    row = conn.execute(
        "SELECT practice_grade FROM progress WHERE module = ? AND step = ?",
        (module, step),
    ).fetchone()
    return row["practice_grade"] if row else None
