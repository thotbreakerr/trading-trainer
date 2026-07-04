"""VWAP reclaim and pullback-hold setups (doc §10). A touch is not a signal —
the HOLD is: `hold_bars` consecutive 1m closes on the right side confirm."""
from __future__ import annotations

from app.detectors.types import DaySnapshot, Signal, default_target


def _vwap_at(snap: DaySnapshot, ts) -> float | None:
    value = None
    for t, v in snap.vwap:
        if t > ts:
            break
        value = v
    return value


def _swing_stop(bars, index: int, direction: str, lookback: int = 6) -> float:
    window = bars[max(0, index - lookback) : index + 1]
    if direction == "long":
        return round(min(b.low for b in window), 2)
    return round(max(b.high for b in window), 2)


def detect_vwap_reclaim(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    """Below VWAP -> closes back above and HOLDS for hold_bars closes.
    Mirrored for a loss-of-VWAP short."""
    hold = int(cfg.get("reclaim_hold_bars", 3))
    rth = snap.rth_bars
    if len(rth) < hold + 2:
        return []
    signals: list[Signal] = []
    for direction in ("long", "short"):
        was_wrong_side = False
        streak = 0
        for i, bar in enumerate(rth):
            vwap = _vwap_at(snap, bar.ts)
            if vwap is None:
                continue
            above = bar.close > vwap
            right_side = above if direction == "long" else not above
            if not right_side:
                was_wrong_side = True
                streak = 0
                continue
            if not was_wrong_side:
                continue  # never lost the line: nothing to reclaim
            streak += 1
            if streak >= hold:
                entry = round(bar.close, 2)
                stop = _swing_stop(rth, i, direction)
                if abs(entry - stop) < 0.01:
                    break
                signals.append(
                    Signal(
                        symbol=snap.symbol, ts=bar.ts,
                        setup_type="vwap_reclaim" if direction == "long" else "vwap_loss",
                        direction=direction, entry=entry, stop=stop,
                        target=default_target(entry, stop, direction, cfg.get("target_rr", 2.0)),
                        context={"vwap": round(vwap, 2), "hold_bars": hold, "rvol": snap.rvol},
                    )
                )
                break
        # one signal max per direction per day (engine dedups too)
    return signals


def detect_vwap_pullback(snap: DaySnapshot, cfg: dict) -> list[Signal]:
    """Trending above VWAP, first touch of the line that holds -> long
    (mirrored short below). 'Held' = touch bar or the next closes back on
    the trend side."""
    hold = int(cfg.get("reclaim_hold_bars", 3))
    min_run = int(cfg.get("pullback_min_run_bars", 10))
    rth = snap.rth_bars
    if len(rth) < min_run + 2:
        return []
    signals: list[Signal] = []
    for direction in ("long", "short"):
        run = 0
        for i, bar in enumerate(rth):
            vwap = _vwap_at(snap, bar.ts)
            if vwap is None:
                continue
            on_side = bar.low > vwap if direction == "long" else bar.high < vwap
            touched = bar.low <= vwap <= bar.high
            if on_side:
                run += 1
                continue
            if touched and run >= min_run:
                confirm = rth[i : i + hold]
                if len(confirm) < hold:
                    break
                held = all(
                    (b.close > vwap) if direction == "long" else (b.close < vwap)
                    for b in confirm[1:]
                ) if hold > 1 else True
                if held:
                    last = confirm[-1]
                    entry = round(last.close, 2)
                    stop = round(vwap - abs(entry - vwap) * 0.5, 2) if direction == "long" else round(
                        vwap + abs(entry - vwap) * 0.5, 2
                    )
                    if abs(entry - stop) < 0.01:
                        break
                    signals.append(
                        Signal(
                            symbol=snap.symbol, ts=last.ts, setup_type="vwap_pullback",
                            direction=direction, entry=entry, stop=stop,
                            target=default_target(entry, stop, direction, cfg.get("target_rr", 2.0)),
                            context={"vwap": round(vwap, 2), "run_bars": run, "rvol": snap.rvol},
                        )
                    )
                break
            run = 0  # crossed the line without a prior run: reset
    return signals
