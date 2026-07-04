"""The grader (doc §10 layer 2): any trade — coach-proposed or user-taken —
scored against a per-setup checklist. The checklist is ALWAYS displayed;
no black box. Pure functions.

Grade = pass count: Textbook / Solid / Risky / Reckless, with two overrides:
- 'Textbook' additionally REQUIRES the volume confluence item (chop
  mitigation) — a full-marks-except-volume breakout is 'low quality —
  likely a trap'.
- Acting on an already-invalidated setup is Reckless, with the reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.detectors.types import DaySnapshot

TIER_ORDER = ["Reckless", "Risky", "Solid", "Textbook"]


def tier_at_least(tier: str, required: str) -> bool:
    return TIER_ORDER.index(tier) >= TIER_ORDER.index(required)


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    label: str
    passed: bool
    detail: str

    def to_json(self) -> dict:
        return {"key": self.key, "label": self.label, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class GradeResult:
    tier: str
    checklist: list[ChecklistItem] = field(default_factory=list)
    note: str | None = None

    def to_json(self) -> dict:
        return {
            "tier": self.tier,
            "note": self.note,
            "checklist": [c.to_json() for c in self.checklist],
        }


BREAKOUT_SETUPS = {"orb_long", "orb_short", "level_break_pdh", "level_break_pdl",
                   "level_break_pmh", "level_break_pml"}


def _trend_direction(snap: DaySnapshot) -> str | None:
    if not snap.ema9_5m or not snap.ema20_5m:
        return None
    fast = snap.ema9_5m[-1][1]
    slow = snap.ema20_5m[-1][1]
    if abs(fast - slow) < 1e-9:
        return None
    return "long" if fast > slow else "short"


def grade_entry(
    direction: str,
    entry: float,
    stop: float,
    target: float | None,
    snap: DaySnapshot,
    grading_cfg: dict,
    *,
    setup_type: str | None = None,
    invalidated: bool = False,
) -> GradeResult:
    min_rr = float(grading_cfg.get("min_rr", 2.0))
    min_rvol = float(grading_cfg.get("min_rvol", 1.5))
    items: list[ChecklistItem] = []

    trend = _trend_direction(snap)
    items.append(
        ChecklistItem(
            "with_trend", "With the trend (9/20 EMA)",
            trend == direction,
            f"5m EMAs point {trend or 'nowhere yet'}, trade is {direction}",
        )
    )

    rvol = snap.rvol
    items.append(
        ChecklistItem(
            "rvol", "Volume confirms (RVOL)",
            rvol is not None and rvol >= min_rvol,
            f"RVOL {rvol:.2f} vs {min_rvol:.1f} required" if rvol is not None else "no RVOL baseline",
        )
    )

    risk = abs(entry - stop)
    rr = (abs(target - entry) / risk) if (target is not None and risk >= 0.01) else None
    items.append(
        ChecklistItem(
            "rr", f"Reward ≥ {min_rr:g}× risk",
            rr is not None and rr >= min_rr,
            f"R:R {rr:.2f}" if rr is not None else "no target or zero risk",
        )
    )

    rth = snap.rth_bars
    if rth and risk >= 0.01:
        window = rth[-8:]
        if direction == "long":
            swing = min(b.low for b in window)
            structural = stop <= swing + 0.25 * risk
            detail = f"stop {stop:.2f} vs recent swing low {swing:.2f}"
        else:
            swing = max(b.high for b in window)
            structural = stop >= swing - 0.25 * risk
            detail = f"stop {stop:.2f} vs recent swing high {swing:.2f}"
    else:
        structural, detail = False, "not enough bars to judge structure"
    items.append(ChecklistItem("stop", "Stop behind structure", structural, detail))

    if rth and risk >= 0.01:
        last = rth[-1].close
        chasing = abs(last - entry) > risk
        detail = f"price {last:.2f} is {abs(last - entry):.2f} from entry {entry:.2f} (1R = {risk:.2f})"
    else:
        chasing, detail = True, "no visible price"
    items.append(ChecklistItem("chase", "Not chasing an extended move", not chasing, detail))

    if invalidated:
        return GradeResult(
            "Reckless", items,
            "acted on an already-invalidated setup — the tell had already failed",
        )

    passes = sum(1 for i in items if i.passed)
    rvol_ok = items[1].passed
    if passes == 5:
        tier = "Textbook"
    elif passes == 4:
        tier = "Solid"
    elif passes == 3:
        tier = "Risky"
    else:
        tier = "Reckless"
    note = None
    if tier == "Textbook" and not rvol_ok:  # defensive: can't happen (rvol is an item)
        tier = "Solid"
    if setup_type in BREAKOUT_SETUPS and not rvol_ok:
        note = "low quality — likely a trap (breakout without volume)"
        if tier == "Textbook":
            tier = "Solid"
    return GradeResult(tier, items, note)


def grade_signal(signal, snap: DaySnapshot, grading_cfg: dict) -> GradeResult:
    """Grade a coach-proposed setup at fire time."""
    if signal.entry is None or signal.stop is None:
        # info signals (gap context, trend state) aren't trades to grade
        return GradeResult("Solid", [], "informational signal")
    return grade_entry(
        signal.direction, signal.entry, signal.stop, signal.target,
        snap, grading_cfg, setup_type=signal.setup_type,
    )
