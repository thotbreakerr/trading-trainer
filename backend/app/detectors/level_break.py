"""Key-level break (doc §10): first 1m close beyond PDH/PDL or the
pre-market high/low fires a break setup in that direction."""
from __future__ import annotations

from app.detectors.types import DaySnapshot, Signal, default_target


def _swing_stop(bars, index: int, direction: str, lookback: int = 6) -> float:
    window = bars[max(0, index - lookback) : index + 1]
    if direction == "long":
        return round(min(b.low for b in window), 2)
    return round(max(b.high for b in window), 2)


def detect_level_break(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    rth = snap.rth_bars
    if len(rth) < 2:
        return []
    lv = snap.levels
    watch = [
        ("pdh", lv.prior_high, "long"),
        ("pmh", lv.premarket_high, "long"),
        ("pdl", lv.prior_low, "short"),
        ("pml", lv.premarket_low, "short"),
    ]
    signals: list[Signal] = []
    fired_dirs: set[str] = set()
    for name, level, direction in watch:
        if level is None or direction in fired_dirs:
            continue
        # the break must actually be a break: the day must have traded on the
        # near side of the level before crossing it
        crossed_from_inside = False
        for i, bar in enumerate(rth):
            inside = bar.close < level if direction == "long" else bar.close > level
            if inside:
                crossed_from_inside = True
                continue
            broke = bar.close > level if direction == "long" else bar.close < level
            if broke and crossed_from_inside:
                entry = round(level, 2)
                stop = _swing_stop(rth, i, direction)
                if abs(entry - stop) < 0.01:
                    break
                signals.append(
                    Signal(
                        symbol=snap.symbol, ts=bar.ts, setup_type=f"level_break_{name}",
                        direction=direction, entry=entry, stop=stop,
                        target=default_target(entry, stop, direction, cfg.get("target_rr", 2.0)),
                        context={"level": round(level, 2), "level_name": name, "rvol": snap.rvol},
                    )
                )
                fired_dirs.add(direction)
                break
    return signals
