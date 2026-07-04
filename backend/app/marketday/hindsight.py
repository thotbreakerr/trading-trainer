"""Hindsight tracking (doc §11.4): every fired setup is followed to its
natural outcome — target, stop, or the close — whether traded or not, so
passed decisions become learnable. Pure; same worst-case bias as the sim
(same-bar stop+target resolves to the stop)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.models import Bar


@dataclass(frozen=True)
class Outcome:
    outcome: str  # 'target' | 'stop' | 'eod' | 'never_triggered'
    r_multiple: float | None
    exit_price: float | None


def track_outcome(
    bars_after: Sequence[Bar],
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> Outcome:
    """Walk bars after the fire: wait for the entry to trade, then first of
    stop/target (stop first on a shared bar), else exit at the last close."""
    risk = abs(entry - stop)
    if risk < 0.01:
        return Outcome("never_triggered", None, None)

    def r_of(exit_price: float) -> float:
        pnl = exit_price - entry if direction == "long" else entry - exit_price
        return round(pnl / risk, 3)

    triggered = False
    last_close: float | None = None
    for bar in bars_after:
        last_close = bar.close
        if not triggered:
            touched = bar.low <= entry <= bar.high
            if not touched:
                continue
            triggered = True
        # stop first — worst case, mirroring the sim (doc §9)
        if direction == "long":
            if bar.low <= stop:
                return Outcome("stop", r_of(stop), stop)
            if bar.high >= target:
                return Outcome("target", r_of(target), target)
        else:
            if bar.high >= stop:
                return Outcome("stop", r_of(stop), stop)
            if bar.low <= target:
                return Outcome("target", r_of(target), target)
    if not triggered:
        return Outcome("never_triggered", None, None)
    assert last_close is not None
    return Outcome("eod", r_of(last_close), last_close)
