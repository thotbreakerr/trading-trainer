"""Shared detector types (doc §10): pure data in, signals out. A detector
never touches the DB or the clock — it reads a DaySnapshot the engine built
from clock-clipped bars, so no-lookahead is inherited, not re-implemented."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.analysis.levels import Levels
from app.models import Bar, CalendarDay, to_db_ts


@dataclass(frozen=True)
class DaySnapshot:
    """Everything one symbol's detectors may see at the clock."""

    symbol: str
    cal: CalendarDay
    bars: list[Bar]  # today's bars <= cutoff (pre + rth), ascending
    levels: Levels
    prior_close: float | None
    vwap: list[tuple[datetime, float]]  # today's RTH vwap points <= cutoff
    rvol: float | None
    ema9_5m: list[tuple[datetime, float]]  # 5m-close EMAs <= cutoff
    ema20_5m: list[tuple[datetime, float]]
    clock: datetime

    @property
    def rth_bars(self) -> list[Bar]:
        return [b for b in self.bars if b.session == "rth"]


@dataclass(frozen=True)
class Signal:
    symbol: str
    ts: datetime  # the confirming bar's start time
    setup_type: str
    direction: str  # 'long' | 'short'
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    context: dict = field(default_factory=dict)

    @property
    def rr(self) -> float | None:
        if self.entry is None or self.stop is None or self.target is None:
            return None
        risk = abs(self.entry - self.stop)
        if risk < 0.01:
            return None
        return round(abs(self.target - self.entry) / risk, 2)

    @property
    def key(self) -> tuple[str, str, str]:
        """Fired-set identity: one fire per setup+direction per day (v1)."""
        return (self.symbol, self.setup_type, self.direction)

    def to_json(self) -> dict:
        return {
            "symbol": self.symbol,
            "ts": to_db_ts(self.ts),
            "setup_type": self.setup_type,
            "direction": self.direction,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "rr": self.rr,
            "context": self.context,
        }


def default_target(entry: float, stop: float, direction: str, rr: float = 2.0) -> float:
    """Doc-consistent default: target = entry + rr x risk (per-setup override
    lives in rules_config.yaml)."""
    risk = abs(entry - stop)
    return round(entry + risk * rr, 2) if direction == "long" else round(entry - risk * rr, 2)
