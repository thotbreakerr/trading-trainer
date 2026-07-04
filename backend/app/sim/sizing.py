"""Position sizing (doc §9): entry + stop + risk %% of equity -> share count.
Pure math; the API and the order ticket both call this one function."""
from __future__ import annotations

import math
from dataclasses import dataclass


class SizingError(ValueError):
    pass


@dataclass(frozen=True)
class Sizing:
    shares: int
    risk_amount: float  # dollars at risk if the stop is hit
    per_share_risk: float
    notional: float
    bp_capped: bool  # True when buying power, not risk, set the size


def size_position(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float = 1.0,
    leverage: float = 4.0,
) -> Sizing:
    if entry <= 0 or stop <= 0:
        raise SizingError("entry and stop must be positive prices")
    per_share = abs(entry - stop)
    if per_share < 0.01:
        raise SizingError("stop must be at least a cent away from entry")
    risk_amount = equity * (risk_pct / 100.0)
    shares_by_risk = math.floor(risk_amount / per_share)
    shares_by_bp = math.floor((equity * leverage) / entry)
    shares = min(shares_by_risk, shares_by_bp)
    if shares < 1:
        raise SizingError(
            f"risk {risk_pct}% of ${equity:,.0f} can't buy one share with a "
            f"${per_share:.2f} stop distance"
        )
    return Sizing(
        shares=shares,
        risk_amount=shares * per_share,
        per_share_risk=per_share,
        notional=shares * entry,
        bp_capped=shares_by_bp < shares_by_risk,
    )
