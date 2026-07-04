"""Opening-range breakout / breakdown (doc §10): the first N minutes set the
range; the first 1m CLOSE beyond it fires the setup."""
from __future__ import annotations

from datetime import timedelta

from app.detectors.types import DaySnapshot, Signal, default_target


def detect_orb(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    minutes = int(cfg.get("minutes", 15))
    rth = snap.rth_bars
    if not rth:
        return []
    or_end = snap.cal.open_utc() + timedelta(minutes=minutes)
    or_bars = [b for b in rth if b.ts < or_end]
    after = [b for b in rth if b.ts >= or_end]
    if not or_bars or not after:
        return []  # range not complete (or nothing after it yet)
    or_high = max(b.high for b in or_bars)
    or_low = min(b.low for b in or_bars)
    signals: list[Signal] = []
    for bar in after:
        if bar.close > or_high:
            signals.append(
                Signal(
                    symbol=snap.symbol, ts=bar.ts, setup_type="orb_long",
                    direction="long", entry=round(or_high, 2), stop=round(or_low, 2),
                    target=default_target(or_high, or_low, "long", cfg.get("target_rr", 2.0)),
                    context={"or_high": round(or_high, 2), "or_low": round(or_low, 2),
                             "or_minutes": minutes, "rvol": snap.rvol},
                )
            )
            break
    for bar in after:
        if bar.close < or_low:
            signals.append(
                Signal(
                    symbol=snap.symbol, ts=bar.ts, setup_type="orb_short",
                    direction="short", entry=round(or_low, 2), stop=round(or_high, 2),
                    target=default_target(or_low, or_high, "short", cfg.get("target_rr", 2.0)),
                    context={"or_high": round(or_high, 2), "or_low": round(or_low, 2),
                             "or_minutes": minutes, "rvol": snap.rvol},
                )
            )
            break
    return signals
