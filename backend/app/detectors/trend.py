"""Trend state via the 9/20 EMA pair on 5-minute closes (doc §6.4, §10):
an information signal fired when alignment appears."""
from __future__ import annotations

from app.detectors.types import DaySnapshot, Signal

MIN_ALIGNED_POINTS = 3  # EMA points (5m bars) the alignment must persist


def detect_trend(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    e9 = snap.ema9_5m
    e20 = snap.ema20_5m
    n = min(len(e9), len(e20))
    if n < MIN_ALIGNED_POINTS:
        return []
    signals: list[Signal] = []
    for direction in ("long", "short"):
        aligned = 0
        for i in range(n):
            fast, slow = e9[i][1], e20[i][1]
            ok = fast > slow if direction == "long" else fast < slow
            aligned = aligned + 1 if ok else 0
            if aligned == MIN_ALIGNED_POINTS:
                signals.append(
                    Signal(
                        symbol=snap.symbol, ts=e9[i][0],
                        setup_type="trend_up" if direction == "long" else "trend_down",
                        direction=direction,
                        context={"ema9": round(fast, 2), "ema20": round(slow, 2)},
                    )
                )
                break
    return signals
