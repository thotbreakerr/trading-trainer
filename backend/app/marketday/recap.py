"""The EOD recap (doc §11): a VIEW composed from setups + trades + briefings —
never a table. Computable on demand for any cached day: if the app never ran
that day, the ledger comes from a batch scan with virtual outcomes."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.detectors.engine import build_snapshot, scan_day
from app.grading.grader import grade_signal
from app.journal import stats
from app.marketday.briefing import get_snapshot
from app.marketday.hindsight import track_outcome
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, FixedClock, eod_clock
from app.models import ET, et_date, from_db_ts, to_db_ts
from app.stores import journal, setups as setups_store


def _batch_ledger(
    conn: sqlite3.Connection, calendar: MarketCalendar, rules_cfg: dict,
    watchlist: list[str], day: date,
) -> list[dict]:
    """Ledger for a day the app never watched: scan + virtual outcomes.
    Computed, not persisted (doc §16.8)."""
    cal_day = calendar.day(day)
    if cal_day is None:
        return []
    out: list[dict] = []
    window = BarWindow(conn, calendar, eod_clock(cal_day), day, lookback_days=1)
    for symbol in watchlist:
        try:
            signals = scan_day(conn, calendar, symbol, day, rules_cfg)
        except ValueError:
            continue
        if not signals:
            continue
        snap = build_snapshot(window, symbol)
        day_bars = [b for b in window.bars_1m(symbol) if et_date(b.ts) == day]
        for sig in signals:
            grade = grade_signal(sig, snap, rules_cfg.get("grading", {}))
            item = {
                "symbol": symbol,
                "fired_ts": to_db_ts(sig.ts),
                "fired_et": sig.ts.astimezone(ET).strftime("%H:%M"),
                "setup_type": sig.setup_type,
                "direction": sig.direction,
                "entry": sig.entry, "stop": sig.stop, "target": sig.target,
                "rr": sig.rr,
                "grade": grade.tier if grade else None,
                "checklist": grade.to_json()["checklist"] if grade else [],
                "status": "computed",
                "taken": 0,
                "note": "computed on demand (app was not watching)",
                "outcome": None,
                "outcome_r": None,
            }
            if sig.entry is not None and sig.stop is not None and sig.target is not None:
                after = [b for b in day_bars if b.ts >= sig.ts]
                outcome = track_outcome(after, sig.direction, sig.entry, sig.stop, sig.target)
                item["outcome"] = outcome.outcome
                item["outcome_r"] = outcome.r_multiple
            out.append(item)
    out.sort(key=lambda i: i["fired_ts"])
    return out


def build_recap(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    rules_cfg: dict,
    watchlist: list[str],
    day: date,
) -> dict:
    ledger = setups_store.list_setups(conn, day, mode="marketday")
    computed = False
    if not ledger:
        ledger = _batch_ledger(conn, calendar, rules_cfg, watchlist, day)
        computed = True

    trades = []
    for row in journal.list_trades(conn, mode="marketday", day=day):
        item = dict(row)
        entry_ts = from_db_ts(item["entry_ts"])
        item["entry_et"] = entry_ts.astimezone(ET).strftime("%H:%M")
        item["review"] = {  # one click reopens the replay at this moment (doc §11)
            "symbol": item["symbol"],
            "day": item["day"],
            "start_at": int((entry_ts).timestamp()) - 300,
        }
        trades.append(item)

    snapshot = get_snapshot(conn, day.isoformat())
    plan_vs_reality: dict = {"taken": snapshot is not None}
    if snapshot:
        cal_day = calendar.day(day)
        reality = []
        for card in snapshot.get("cards", []):
            symbol = card["symbol"]
            actual: dict = {"symbol": symbol, "planned_gap_pct": card.get("gap_pct")}
            if cal_day is not None:
                window = BarWindow(conn, calendar, eod_clock(cal_day), day, lookback_days=1)
                bars = [
                    b for b in window.bars_1m(symbol)
                    if et_date(b.ts) == day and b.session == "rth"
                ]
                if bars:
                    open_price = bars[0].open
                    close_price = bars[-1].close
                    high = max(b.high for b in bars)
                    low = min(b.low for b in bars)
                    actual.update(
                        {
                            "open": open_price,
                            "close": close_price,
                            "day_change_pct": round((close_price / open_price - 1) * 100, 2),
                            "range_pct": round((high - low) / open_price * 100, 2),
                            "broke_pdh": bool(card.get("prior_high") and high > card["prior_high"]),
                            "broke_pdl": bool(card.get("prior_low") and low < card["prior_low"]),
                        }
                    )
            reality.append(actual)
        plan_vs_reality["focus_was"] = [f["symbol"] for f in snapshot.get("focus", [])]
        plan_vs_reality["reality"] = reality

    return {
        "day": day.isoformat(),
        "ledger": ledger,
        "ledger_computed_on_demand": computed,
        "trades": trades,
        "plan_vs_reality": plan_vs_reality,
        "trajectory": stats.trajectory(conn, mode="marketday"),
    }
