"""Indicator math — pure functions over in-memory bar lists. No I/O, no DB,
no clock: callers (BarWindow, detectors, briefing) hand in already-clipped
bars, so nothing here can look ahead.

Scope is deliberately small (doc §6 scope call: no indicator zoo): VWAP,
EMA 9/20, SMA 200 context, and cumulative time-of-day relative volume.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from app.models import ET, SESSION_RTH, Bar


def vwap_series(bars: Sequence[Bar]) -> list[tuple[datetime, float]]:
    """Intraday VWAP anchored at each day's first RTH bar (the doc's 'intraday
    anchor'), typical price × volume. Resets every ET trading date; pre/post
    bars carry no VWAP point."""
    out: list[tuple[datetime, float]] = []
    cum_pv = 0.0
    cum_v = 0
    current_day = None
    for b in bars:
        if b.session != SESSION_RTH:
            continue
        day = b.ts.astimezone(ET).date()
        if day != current_day:
            current_day = day
            cum_pv = 0.0
            cum_v = 0
        typical = (b.high + b.low + b.close) / 3.0
        cum_pv += typical * b.volume
        cum_v += b.volume
        if cum_v > 0:
            out.append((b.ts, cum_pv / cum_v))
    return out


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """Standard EMA (k = 2/(period+1)), seeded with the first value. Length
    matches the input; early values are naturally less smoothed."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def sma(values: Sequence[float], period: int) -> float | None:
    """Simple average of the LAST `period` values (context number, e.g.
    SMA200 of daily closes). None when there is not enough history."""
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def et_minutes(ts: datetime) -> int:
    """Minutes since ET midnight — the clock axis RVOL compares along."""
    local = ts.astimezone(ET)
    return local.hour * 60 + local.minute


def cumulative_volume_at(bars: Sequence[Bar], at_et_minutes: int) -> int:
    """Volume traded up to (and including) an ET clock time — robust to
    missing minutes because it sums what exists rather than indexing."""
    return sum(b.volume for b in bars if et_minutes(b.ts) <= at_et_minutes)


def rvol_at(
    today: Sequence[Bar],
    baseline_days: Sequence[Sequence[Bar]],
    at_et_minutes: int,
) -> float | None:
    """Cumulative time-of-day relative volume (doc §16.4): today's volume so
    far ÷ the baseline mean at the same ET clock time. None without a usable
    baseline. Half days compare naturally (both cut off at the same clock)."""
    baselines = [
        cumulative_volume_at(day_bars, at_et_minutes) for day_bars in baseline_days
    ]
    baselines = [v for v in baselines if v > 0]
    if not baselines:
        return None
    mean = sum(baselines) / len(baselines)
    return cumulative_volume_at(today, at_et_minutes) / mean
