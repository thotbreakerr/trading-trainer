"""Relative-volume spike (doc §10): an information signal, not a trade —
it upgrades everything else that fires while it's true."""
from __future__ import annotations

from app.detectors.types import DaySnapshot, Signal


def detect_rvol_spike(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    threshold = float(cfg.get("threshold", 2.0))
    if snap.rvol is None or snap.rvol < threshold:
        return []
    rth = snap.rth_bars
    if not rth:
        return []
    return [
        Signal(
            symbol=snap.symbol, ts=rth[-1].ts, setup_type="rvol_spike",
            direction="long" if rth[-1].close >= rth[0].open else "short",
            context={"rvol": round(snap.rvol, 2), "threshold": threshold},
        )
    ]
