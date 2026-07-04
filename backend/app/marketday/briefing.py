"""The morning briefing (doc §11): generated on demand from cached pre-market
bars, snapshot saved — the saved snapshot is what the EOD recap grades the
plan against. Refreshing regenerates the VIEW; the snapshot stays."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from app.marketdata.calendar import CalendarUnavailable, MarketCalendar
from app.marketdata.window import BarWindow
from app.models import CT, ET, CalendarDay, to_db_ts


def _fmt_times(ts: datetime) -> dict:
    return {
        "epoch": int(ts.timestamp()),
        "ct": ts.astimezone(CT).strftime("%I:%M %p").lstrip("0"),
        "et": ts.astimezone(ET).strftime("%I:%M %p").lstrip("0"),
    }


def build_briefing(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    watchlist: list[str],
    unlocked: set[str],
    cal_day: CalendarDay,
    clock,
    created_at: datetime,
) -> dict:
    cards = []
    for symbol in watchlist:
        card: dict = {"symbol": symbol}
        try:
            window = BarWindow(conn, calendar, clock, cal_day.day, lookback_days=1)
            daily = window.daily(symbol, 1)
            prior = daily[-1] if daily else None
            levels = window.levels(symbol)
            bars = window.bars_1m(symbol)
            today = [b for b in bars if b.ts >= cal_day.session_open_utc()]
            last = today[-1].close if today else None
            opened = cal_day.open_utc() <= clock.now()
            ref = None
            if opened:
                rth = [b for b in today if b.session == "rth"]
                ref = rth[0].open if rth else last
            else:
                ref = last  # pre-market: gap estimate from the latest print
            card.update(
                {
                    "last_price": last,
                    "gap_pct": round((ref / prior.close - 1) * 100, 2)
                    if (ref and prior and prior.close) else None,
                    "premarket_rvol": window.rvol(symbol),
                    "premarket_high": levels.premarket_high,
                    "premarket_low": levels.premarket_low,
                    "prior_high": levels.prior_high,
                    "prior_low": levels.prior_low,
                    "prior_close": levels.prior_close,
                    "sma200": window.sma200(symbol),
                }
            )
            near = [
                ("PDH", levels.prior_high), ("PDL", levels.prior_low),
                ("PDC", levels.prior_close), ("PMH", levels.premarket_high),
                ("PML", levels.premarket_low),
            ]
            near = [(n, v) for n, v in near if v is not None and last]
            if near and last:
                name, value = min(near, key=lambda nv: abs(nv[1] - last))
                card["nearest_level"] = {
                    "name": name, "price": value,
                    "distance_pct": round((value / last - 1) * 100, 2),
                }
            sma = card.get("sma200")
            card["daily_trend"] = (
                "above the 200-SMA" if (sma and last and last > sma)
                else "below the 200-SMA" if (sma and last) else "unknown"
            )
        except CalendarUnavailable:
            card["error"] = "no data"
        cards.append(card)

    def heat(card: dict) -> float:
        gap = abs(card.get("gap_pct") or 0.0)
        rvol = card.get("premarket_rvol") or 0.0
        return gap * max(rvol, 0.1)

    focus = sorted((c for c in cards if not c.get("error")), key=heat, reverse=True)[:3]
    focus_list = []
    for card in focus:
        gap = card.get("gap_pct")
        rvol = card.get("premarket_rvol")
        nearest = card.get("nearest_level")
        what = []
        if gap is not None and abs(gap) >= 0.5:
            what.append(f"gapping {'up' if gap > 0 else 'down'} {abs(gap):.1f}%")
        if rvol is not None and rvol >= 1.3:
            what.append(f"pre-market volume {rvol:.1f}× normal")
        if nearest:
            what.append(
                f"opening near {nearest['name']} {nearest['price']:.2f} — watch the reaction there"
            )
        focus_list.append(
            {
                "symbol": card["symbol"],
                "why": ", ".join(what) or "quiet so far — range day until proven otherwise",
            }
        )

    setups_in_play = sorted(unlocked)
    key_times = {
        "open": _fmt_times(cal_day.open_utc()),
        "or_complete": _fmt_times(cal_day.open_utc() + timedelta(minutes=15)),
        "reversal_window": _fmt_times(cal_day.open_utc() + timedelta(minutes=30)),
        "flatten_warning": _fmt_times(cal_day.close_utc() - timedelta(minutes=10)),
        "close": _fmt_times(cal_day.close_utc()),
    }

    briefing = {
        "day": cal_day.day.isoformat(),
        "half_day": cal_day.is_half_day,
        "created_at": to_db_ts(created_at),
        "cards": cards,
        "focus": focus_list,
        "game_plan": {
            "setups_in_play": setups_in_play,
            "key_times": key_times,
            "note": "Times shown in CT with ET labels (doc §11)."
            if setups_in_play
            else "No setups unlocked yet — observe mode: watch the open with the map drawn.",
        },
    }
    return briefing


def save_snapshot(conn: sqlite3.Connection, briefing: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO briefings (day, created_at, snapshot) VALUES (?, ?, ?)",
        (briefing["day"], briefing["created_at"], json.dumps(briefing)),
    )


def get_snapshot(conn: sqlite3.Connection, day: str) -> dict | None:
    row = conn.execute("SELECT snapshot FROM briefings WHERE day = ?", (day,)).fetchone()
    return json.loads(row["snapshot"]) if row else None
