"""Gap detection (doc §10): gap up/down context at the open, plus the
gap-fill setup when price turns back through the open toward yesterday."""
from __future__ import annotations

from app.detectors.types import DaySnapshot, Signal


def detect_gap(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    """Fires once on the first RTH bar when |gap| clears the threshold."""
    rth = snap.rth_bars
    if not rth or snap.prior_close is None or snap.prior_close <= 0:
        return []
    first = rth[0]
    gap_pct = (first.open / snap.prior_close - 1.0) * 100
    if abs(gap_pct) < cfg.get("min_gap_pct", 2.0):
        return []
    direction = "long" if gap_pct > 0 else "short"
    return [
        Signal(
            symbol=snap.symbol,
            ts=first.ts,
            setup_type="gap_up" if gap_pct > 0 else "gap_down",
            direction=direction,
            context={"gap_pct": round(gap_pct, 2), "prior_close": snap.prior_close},
        )
    ]


def detect_gap_fill(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    """After a real gap, a 1m close back through the OPEN price in the fill
    direction proposes a trade toward yesterday's close."""
    rth = snap.rth_bars
    if len(rth) < 3 or snap.prior_close is None or snap.prior_close <= 0:
        return []
    open_price = rth[0].open
    gap_pct = (open_price / snap.prior_close - 1.0) * 100
    if abs(gap_pct) < cfg.get("min_gap_pct", 2.0):
        return []
    day_high = max(b.high for b in rth)
    day_low = min(b.low for b in rth)
    if gap_pct > 0:  # gap up: fill trade is SHORT back through the open
        for bar in rth[1:]:
            if bar.close < open_price:
                return [
                    Signal(
                        symbol=snap.symbol, ts=bar.ts, setup_type="gap_fill",
                        direction="short", entry=round(bar.close, 2),
                        stop=round(day_high, 2), target=round(snap.prior_close, 2),
                        context={"gap_pct": round(gap_pct, 2), "open": open_price},
                    )
                ]
    else:  # gap down: fill trade is LONG back through the open
        for bar in rth[1:]:
            if bar.close > open_price:
                return [
                    Signal(
                        symbol=snap.symbol, ts=bar.ts, setup_type="gap_fill",
                        direction="long", entry=round(bar.close, 2),
                        stop=round(day_low, 2), target=round(snap.prior_close, 2),
                        context={"gap_pct": round(gap_pct, 2), "open": open_price},
                    )
                ]
    return []
