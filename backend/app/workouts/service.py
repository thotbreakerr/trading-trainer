"""Deterministic weakness scoring and persistent daily workout plans."""
from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter
from datetime import date

from app.drill import service as drills
from app.models import to_db_ts, utcnow

GRADE_PENALTY = {"Textbook": 0.0, "Solid": 0.25, "Risky": 0.75, "Reckless": 1.0}


def _concept_rows(conn: sqlite3.Connection, concept: str) -> list[sqlite3.Row]:
    prefixes = drills.DRILLABLE[concept]
    clauses = " OR ".join("setup_type LIKE ?" for _ in prefixes)
    return conn.execute(
        f"SELECT * FROM setups WHERE mode = 'drill' AND ({clauses}) ORDER BY day DESC, fired_ts DESC",
        tuple(f"{prefix}%" for prefix in prefixes),
    ).fetchall()


def _mistakes(conn: sqlite3.Connection, concept: str) -> Counter:
    prefixes = drills.DRILLABLE[concept]
    clauses = " OR ".join("s.setup_type LIKE ?" for _ in prefixes)
    rows = conn.execute(
        "SELECT r.mistakes FROM trade_reviews r JOIN trades t ON t.id = r.trade_id "
        "JOIN setups s ON s.id = t.setup_id WHERE " + clauses,
        tuple(f"{prefix}%" for prefix in prefixes),
    )
    out: Counter = Counter()
    for row in rows:
        try:
            out.update(json.loads(row["mistakes"] or "[]"))
        except (TypeError, json.JSONDecodeError):
            pass
    return out


def weakness_scores(conn: sqlite3.Connection, concepts: set[str], day: date) -> list[dict]:
    scored = []
    for concept in concepts:
        rows = _concept_rows(conn, concept)
        grades = [r["user_grade"] for r in rows if r["taken"] and r["user_grade"]]
        recent = grades[:10]
        grade_penalty = sum(GRADE_PENALTY.get(g, 0.5) for g in recent) / len(recent) if recent else 0.65
        scarcity = 1.0 / (1.0 + len(rows) / 5.0)
        recency = 1.0
        if rows:
            days_ago = max(0, (day - date.fromisoformat(rows[0]["day"])).days)
            recency = min(days_ago / 14.0, 1.0)
        passed = [r for r in rows[:10] if not r["taken"]]
        missed_opportunity = sum(1 for r in passed if (r["outcome_r"] or 0) >= 1.0) / max(len(passed), 1)
        score = round(grade_penalty * 2.0 + scarcity + recency * 0.5 + missed_opportunity * 0.5, 3)
        mistakes = _mistakes(conn, concept)
        if not rows:
            reason = "Cold start: build a baseline for this setup."
        elif mistakes:
            mistake, count = mistakes.most_common(1)[0]
            reason = f"Recent reviews flag “{mistake}” {count} time{'s' if count != 1 else ''}."
        elif recent and grade_penalty >= 0.6:
            risky = sum(g in ("Risky", "Reckless") for g in recent)
            reason = f"{risky} of the last {len(recent)} taken reps were Risky or Reckless."
        elif missed_opportunity:
            reason = "Recent passes included positive-R opportunities; practice recognition."
        else:
            reason = "This setup is least recent and keeps today’s practice diverse."
        scored.append({"setup": concept, "score": score, "reason": reason, "attempts": len(rows)})
    # Stable daily tie-break keeps cold-start plans varied but reproducible.
    rng = random.Random(day.isoformat())
    rng.shuffle(scored)
    return sorted(scored, key=lambda item: item["score"], reverse=True)


def daily_plan(conn: sqlite3.Connection, lessons, rules_cfg: dict, day: date) -> dict:
    existing = conn.execute("SELECT * FROM workout_runs WHERE day = ?", (day.isoformat(),)).fetchone()
    if existing is None:
        concepts = drills.unlocked_drillable(conn, lessons, rules_cfg)
        if not concepts:
            return {"unlocked": False, "gate_module": drills.GATE_MODULE, "run": None, "items": []}
        ranked = weakness_scores(conn, concepts, day)[:3]
        now = to_db_ts(utcnow())
        run_id = conn.execute(
            "INSERT INTO workout_runs (day, status, created_at) VALUES (?, 'active', ?)",
            (day.isoformat(), now),
        ).lastrowid
        for position, item in enumerate(ranked):
            conn.execute(
                "INSERT INTO workout_items (run_id, position, setup, reps, weakness_score, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, position, item["setup"], 3, item["score"], item["reason"]),
            )
        existing = conn.execute("SELECT * FROM workout_runs WHERE id = ?", (run_id,)).fetchone()
    items = conn.execute(
        "SELECT * FROM workout_items WHERE run_id = ? ORDER BY position", (existing["id"],)
    ).fetchall()
    return {
        "unlocked": True,
        "run": dict(existing),
        "items": [
            {**dict(item), "label": drills.LABELS.get(item["setup"], item["setup"].replace("_", " ").title())}
            for item in items
        ],
    }


def complete_item(conn: sqlite3.Connection, run_id: int, item_id: int) -> dict:
    item = conn.execute(
        "SELECT * FROM workout_items WHERE id = ? AND run_id = ?", (item_id, run_id)
    ).fetchone()
    if item is None:
        raise KeyError(item_id)
    now = to_db_ts(utcnow())
    conn.execute(
        "UPDATE workout_items SET status = 'complete', completed_at = ? WHERE id = ?", (now, item_id)
    )
    pending = conn.execute(
        "SELECT COUNT(*) FROM workout_items WHERE run_id = ? AND status != 'complete'", (run_id,)
    ).fetchone()[0]
    if pending == 0:
        conn.execute(
            "UPDATE workout_runs SET status = 'complete', completed_at = ? WHERE id = ?", (now, run_id)
        )
    return {"run_id": run_id, "item_id": item_id, "status": "complete", "run_complete": pending == 0}
