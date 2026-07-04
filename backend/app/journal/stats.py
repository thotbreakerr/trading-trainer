"""Trajectory statistics (doc §11, §14): win rate, average R, expectancy,
and the grade distribution over time — always DERIVED from the trades table
at read time, never stored."""
from __future__ import annotations

import sqlite3
from collections import Counter


def _summary(rows: list[dict]) -> dict:
    closed = [r for r in rows if r.get("r_multiple") is not None]
    wins = [r for r in closed if r["r_multiple"] > 0]
    losses = [r for r in closed if r["r_multiple"] <= 0]
    n = len(closed)
    return {
        "trades": n,
        "win_rate": round(len(wins) / n, 3) if n else None,
        "avg_win_r": round(sum(r["r_multiple"] for r in wins) / len(wins), 2) if wins else None,
        "avg_loss_r": round(sum(r["r_multiple"] for r in losses) / len(losses), 2) if losses else None,
        "avg_r": round(sum(r["r_multiple"] for r in closed) / n, 3) if n else None,
        "expectancy_r": round(sum(r["r_multiple"] for r in closed) / n, 3) if n else None,
        "total_r": round(sum(r["r_multiple"] for r in closed), 2) if n else 0.0,
    }


def trajectory(conn: sqlite3.Connection, mode: str | None = None) -> dict:
    sql = "SELECT day, r_multiple, grade FROM trades"
    args: list = []
    if mode:
        sql += " WHERE mode = ?"
        args.append(mode)
    sql += " ORDER BY day, entry_ts"
    rows = [dict(r) for r in conn.execute(sql, args)]

    grade_by_day: dict[str, Counter] = {}
    for r in rows:
        grade_by_day.setdefault(r["day"], Counter())[r["grade"] or "ungraded"] += 1

    return {
        "cumulative": _summary(rows),
        "rolling_20": _summary(rows[-20:]),
        "grade_distribution": dict(sum((c for c in grade_by_day.values()), Counter())),
        "grade_by_day": [
            {"day": day, "grades": dict(counts)} for day, counts in sorted(grade_by_day.items())
        ],
        "equity_curve_r": _equity_curve(rows),
    }


def _equity_curve(rows: list[dict]) -> list[dict]:
    total = 0.0
    out = []
    for r in rows:
        if r.get("r_multiple") is None:
            continue
        total += r["r_multiple"]
        out.append({"day": r["day"], "cum_r": round(total, 2)})
    return out
