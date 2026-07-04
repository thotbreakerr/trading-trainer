"""Detector orchestration (doc §10).

Structural rules encoded here:
- SAME ENGINE BOTH MODES: batch is literally the live loop stepped minute by
  minute over a clock-bound BarWindow — equivalence is by construction and
  still asserted in tests.
- Signals fire once per (symbol, setup, direction) per day via the fired-set.
- Unlock filtering is presentation policy: callers pass the unlocked set to
  filter, or None to compute everything (ledger/recap/hindsight need all).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from app.analysis.indicators import ema_series, et_minutes
from app.detectors.gap import detect_gap, detect_gap_fill
from app.detectors.level_break import detect_level_break
from app.detectors.orb import detect_orb
from app.detectors.rvol import detect_rvol_spike
from app.detectors.trend import detect_trend
from app.detectors.types import DaySnapshot, Signal
from app.detectors.vwap_setups import detect_vwap_pullback, detect_vwap_reclaim
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow, ReplayClock, RvolBaseline
from app.models import et_date

# (detector fn, key into rules_config['detectors'], key into rules_config['unlocks'])
REGISTRY: list[tuple[str, object, str, str]] = [
    ("gap", detect_gap, "gap", "gap_context"),
    ("gap_fill", detect_gap_fill, "gap", "gap_fill"),
    ("orb", detect_orb, "opening_range", "opening_range_breakout"),
    ("vwap_reclaim", detect_vwap_reclaim, "vwap", "vwap_reclaim"),
    ("vwap_pullback", detect_vwap_pullback, "vwap", "vwap_pullback"),
    ("level_break", detect_level_break, "level_break", "level_break"),
    ("rvol_spike", detect_rvol_spike, "rvol_spike", "rvol_spike"),
    ("trend", detect_trend, "trend", "trend_state"),
]


def build_snapshot(
    window: BarWindow, symbol: str, *, rvol_baseline: RvolBaseline | None = None
) -> DaySnapshot:
    """Everything detectors may see, assembled from clock-clipped reads."""
    anchor = window.anchor
    all_bars = window.bars_1m(symbol)
    today = [b for b in all_bars if et_date(b.ts) == anchor.day]
    daily = window.daily(symbol, 1)
    prior_close = daily[-1].close if daily else None
    vwap_today = [(t, v) for t, v in window.vwap(symbol) if et_date(t) == anchor.day]
    five = [b for b in window.bars(symbol, "5m") if et_date(b.ts) == anchor.day and b.session == "rth"]
    closes = [b.close for b in five]
    times = [b.ts for b in five]
    clock = window.clock.now()
    if rvol_baseline is not None:
        cutoff = min(window.cutoff(), anchor.session_close_utc())
        rvol = rvol_baseline.rvol(today, et_minutes(cutoff))
    else:
        rvol = window.rvol(symbol)
    return DaySnapshot(
        symbol=symbol,
        cal=anchor,
        bars=today,
        levels=window.levels(symbol),
        prior_close=prior_close,
        vwap=vwap_today,
        rvol=rvol,
        ema9_5m=list(zip(times, ema_series(closes, 9))),
        ema20_5m=list(zip(times, ema_series(closes, 20))),
        clock=clock,
    )


def run_detectors(
    snap: DaySnapshot,
    rules_cfg: dict,
    fired: set,
    unlocked: set[str] | None = None,
) -> list[Signal]:
    detector_cfg = rules_cfg.get("detectors", {})
    out: list[Signal] = []
    for _name, fn, cfg_key, unlock_key in REGISTRY:
        if unlocked is not None and unlock_key not in unlocked:
            continue
        for signal in fn(snap, detector_cfg.get(cfg_key, {}) or {}):  # type: ignore[operator]
            if signal.key in fired:
                continue
            fired.add(signal.key)
            out.append(signal)
    return out


def scan_day(
    conn: sqlite3.Connection,
    calendar: MarketCalendar,
    symbol: str,
    day: date,
    rules_cfg: dict,
    unlocked: set[str] | None = None,
) -> list[Signal]:
    """Batch mode: the live loop, stepped bar by bar across the whole day."""
    cal_day = calendar.day(day)
    if cal_day is None:
        raise ValueError(f"{day} is not a trading day")
    clock = ReplayClock(cal_day.open_utc())
    window = BarWindow(conn, calendar, clock, day, lookback_days=1)
    baseline = RvolBaseline.load(conn, calendar, symbol, day)
    fired: set = set()
    signals: list[Signal] = []
    while clock.current < cal_day.close_utc():
        clock.current = clock.current + timedelta(minutes=1)
        snap = build_snapshot(window, symbol, rvol_baseline=baseline)
        signals += run_detectors(snap, rules_cfg, fired, unlocked)
    return signals


def live_signals(
    window: BarWindow,
    symbol: str,
    rules_cfg: dict,
    fired: set,
    unlocked: set[str] | None = None,
    rvol_baseline: RvolBaseline | None = None,
) -> list[Signal]:
    """One live tick: exactly what scan_day runs per minute."""
    snap = build_snapshot(window, symbol, rvol_baseline=rvol_baseline)
    return run_detectors(snap, rules_cfg, fired, unlocked)


def unlocked_setups(rules_cfg: dict, completed_modules: set[int]) -> set[str]:
    """Unlock keys whose module is complete (doc §12)."""
    unlocks: dict[str, int] = rules_cfg.get("unlocks", {}) or {}
    return {key for key, module in unlocks.items() if module in completed_modules}
