"""Key-level math (doc §6 module 3) — pure functions, no I/O.

Levels the curriculum teaches: prior day high/low/close, pre-market
high/low, round numbers, and swing points. Callers pass already-clipped
bars, so nothing here can look ahead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.models import SESSION_PRE, Bar, DailyBar


@dataclass(frozen=True)
class Levels:
    prior_high: float | None
    prior_low: float | None
    prior_close: float | None
    premarket_high: float | None
    premarket_low: float | None


def prior_day_levels(daily: Sequence[DailyBar]) -> tuple[float | None, float | None, float | None]:
    if not daily:
        return None, None, None
    last = daily[-1]
    return last.high, last.low, last.close


def premarket_high_low(today_bars: Sequence[Bar]) -> tuple[float | None, float | None]:
    pre = [b for b in today_bars if b.session == SESSION_PRE]
    if not pre:
        return None, None
    return max(b.high for b in pre), min(b.low for b in pre)


def build_levels(daily: Sequence[DailyBar], today_bars: Sequence[Bar]) -> Levels:
    ph, pl, pc = prior_day_levels(daily)
    pmh, pml = premarket_high_low(today_bars)
    return Levels(
        prior_high=ph, prior_low=pl, prior_close=pc,
        premarket_high=pmh, premarket_low=pml,
    )


def round_numbers(price: float, span_pct: float = 1.5) -> list[float]:
    """Whole and half dollars near price for cheap stocks; whole/`$5` levels
    for expensive ones — the psychological levels module 3 points at."""
    if price <= 0:
        return []
    step = 0.5 if price < 50 else (1.0 if price < 250 else 5.0)
    lo = price * (1 - span_pct / 100)
    hi = price * (1 + span_pct / 100)
    first = int(lo / step) * step
    out = []
    level = first
    while level <= hi:
        if level >= lo:
            out.append(round(level, 2))
        level += step
    return out


def swing_points(bars: Sequence[Bar], strength: int = 3) -> tuple[list[Bar], list[Bar]]:
    """Fractal swing highs/lows: a bar whose high (low) beats `strength`
    neighbors on both sides. Returns (swing_highs, swing_lows)."""
    highs: list[Bar] = []
    lows: list[Bar] = []
    n = len(bars)
    for i in range(strength, n - strength):
        left = bars[i - strength : i]
        right = bars[i + 1 : i + 1 + strength]
        b = bars[i]
        if all(b.high > x.high for x in left) and all(b.high >= x.high for x in right):
            highs.append(b)
        if all(b.low < x.low for x in left) and all(b.low <= x.low for x in right):
            lows.append(b)
    return highs, lows
