"""Shared risk policy used by replay, scenario, drill, and Market Day entries."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app.models import to_db_ts


def policy_json(cfg) -> dict:
    return {
        "mode": cfg.risk_mode if cfg.risk_mode in ("coach", "enforce") else "coach",
        "max_risk_per_trade_pct": cfg.max_risk_per_trade_pct,
        "max_daily_loss_r": cfg.max_daily_loss_r,
        "max_trades_per_day": cfg.max_trades_per_day,
        "cooldown_minutes": cfg.cooldown_minutes,
        "max_open_risk_pct": cfg.max_open_risk_pct,
        "require_protective_stop": cfg.require_protective_stop,
    }


def _open_risk(sim) -> float:
    total = 0.0
    for position in sim.positions.values():
        if position.initial_stop is not None:
            total += abs(position.avg_price - position.initial_stop) * abs(position.qty)
    for entry in sim.orders.values():
        if entry.status != "working" or entry.role != "entry" or not entry.bracket_id:
            continue
        stop = next(
            (o for o in sim.orders.values() if o.bracket_id == entry.bracket_id and o.role == "stop"),
            None,
        )
        ref = entry.limit_price or sim.last_close.get(entry.symbol)
        if stop is not None and stop.stop_price is not None and ref is not None:
            total += abs(ref - stop.stop_price) * entry.qty
    return total


def usage(sim, now: datetime, cfg) -> dict:
    closed = [trade for trade in sim.trades if trade.closed]
    closed_r = round(sum(trade.r_multiple or 0.0 for trade in closed), 3)
    last_exit = max((trade.exit_ts for trade in closed if trade.exit_ts is not None), default=None)
    cooldown_remaining = 0
    if last_exit is not None:
        remaining = timedelta(minutes=cfg.cooldown_minutes) - (now - last_exit)
        seconds = max(0, remaining.total_seconds())
        cooldown_remaining = int(seconds // 60 + (seconds % 60 > 0))
    equity = sim.equity()
    open_risk = _open_risk(sim)
    return {
        "closed_r": closed_r,
        "trades": len(sim.trades),
        "open_risk_amount": round(open_risk, 2),
        "open_risk_pct": round(open_risk / equity * 100, 3) if equity > 0 else None,
        "cooldown_remaining_minutes": cooldown_remaining,
    }


def evaluate_entry(sim, cfg, now: datetime, qty: int, entry: float, stop: float | None) -> dict:
    limits = policy_json(cfg)
    current = usage(sim, now, cfg)
    issues: list[dict] = []

    def issue(key: str, detail: str) -> None:
        issues.append({"rule_key": key, "detail": detail})

    if limits["require_protective_stop"] and stop is None:
        issue("protective_stop", "Every new position requires a defined protective stop.")
    proposed = abs(entry - stop) * qty if stop is not None else 0.0
    equity = sim.equity()
    proposed_pct = proposed / equity * 100 if equity > 0 else 0.0
    if stop is not None and proposed_pct > limits["max_risk_per_trade_pct"] + 1e-6:
        issue(
            "max_risk_per_trade",
            f"Proposed risk {proposed_pct:.2f}% exceeds {limits['max_risk_per_trade_pct']:.2f}% per trade.",
        )
    if current["closed_r"] <= -limits["max_daily_loss_r"]:
        issue(
            "max_daily_loss",
            f"Session P/L is {current['closed_r']:.2f}R; daily stop is -{limits['max_daily_loss_r']:.2f}R.",
        )
    if current["trades"] >= limits["max_trades_per_day"]:
        issue("max_trades", f"Trade limit reached ({current['trades']}/{limits['max_trades_per_day']}).")
    if current["cooldown_remaining_minutes"] > 0:
        issue("cooldown", f"Wait {current['cooldown_remaining_minutes']} more minute(s) after the last exit.")
    combined_pct = (current["open_risk_amount"] + proposed) / equity * 100 if equity > 0 else 0.0
    if combined_pct > limits["max_open_risk_pct"] + 1e-6:
        issue(
            "max_open_risk",
            f"Combined open risk {combined_pct:.2f}% exceeds {limits['max_open_risk_pct']:.2f}%.",
        )
    disposition = "blocked" if issues and limits["mode"] == "enforce" else "warned"
    return {
        "allowed": not issues or limits["mode"] == "coach",
        "mode": limits["mode"],
        "issues": [{**item, "disposition": disposition} for item in issues],
        "proposed_risk_amount": round(proposed, 2),
        "proposed_risk_pct": round(proposed_pct, 3),
        "usage": current,
        "policy": limits,
    }


def record(
    conn: sqlite3.Connection,
    decision: dict,
    *,
    session_id: str | None,
    mode: str,
    day,
    now: datetime,
    action: str,
) -> None:
    for item in decision["issues"]:
        conn.execute(
            "INSERT INTO risk_events (session_id, mode, day, ts, rule_key, action, disposition, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, mode, day.isoformat(), to_db_ts(now), item["rule_key"], action,
                item["disposition"], item["detail"],
            ),
        )


def status(conn: sqlite3.Connection, sim, cfg, now: datetime, session_id: str | None) -> dict:
    recent = conn.execute(
        "SELECT rule_key, action, disposition, detail, ts FROM risk_events "
        "WHERE session_id IS ? ORDER BY ts DESC LIMIT 10",
        (session_id,),
    ).fetchall()
    return {"policy": policy_json(cfg), "usage": usage(sim, now, cfg), "events": [dict(row) for row in recent]}
