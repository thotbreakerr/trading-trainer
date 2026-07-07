"""Shared chart-series assembly for session bars AND step deltas (doc §8).

chart_series() is the one place the bars/overlays/rvol payload is computed;
slice_step_delta() cuts the trailing part a step touched so the client can
merge instead of refetching every second.

Merge contract (mirrored by frontend/src/lib/mergeStepDelta.ts and enforced
by tests/test_step_delta.py): per series, drop every cached element with
t >= delta_series[0].t, then append the delta series; an empty delta series
keeps the cached one; clock/done/rvol always overwrite.

Why trailing slices are exact:
- bars/ema: bucket_start is monotone in bar ts, so slicing the aggregated
  array at the first new 1m bar's bucket yields exactly the touched buckets —
  the upserted partial bucket (open fixed, h/l/c/v moved) plus new ones.
  ema_series is a forward recursion: points before that bucket never change.
- vwap: cumulative per-1m points — old points never change, new points map
  1:1 to newly revealed RTH minutes, so the tail starts at the 1m ts itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from app.analysis.indicators import ema_series
from app.api.serialize import bar_json, point_json
from app.marketdata.aggregate import TF_MINUTES, bucket_start
from app.marketdata.window import BarWindow
from app.models import Bar, CalendarDay, et_date


@dataclass(frozen=True)
class ChartSeries:
    bars: list[Bar]
    vwap: list[tuple[datetime, float]]  # per-1m RTH points
    ema9: list[tuple[datetime, float]]  # per-aggregated-bar points
    ema20: list[tuple[datetime, float]]
    rvol: float | None


def chart_series(
    window: BarWindow, symbol: str, tf: str, *, rvol_baseline_days: int = 20
) -> ChartSeries:
    agg = window.bars(symbol, tf)
    closes = [b.close for b in agg]
    times = [b.ts for b in agg]
    return ChartSeries(
        bars=agg,
        vwap=window.vwap(symbol),
        ema9=list(zip(times, ema_series(closes, 9))),
        ema20=list(zip(times, ema_series(closes, 20))),
        rvol=window.rvol(symbol, baseline_days=rvol_baseline_days),
    )


def slice_step_delta(
    full: ChartSeries, new_1m: list[Bar], tf: str, day_map: Mapping[date, CalendarDay]
) -> ChartSeries:
    """Trailing slice covering exactly the buckets/points this step touched.

    Zero new bars (gap minutes, done/EOD step) → empty series; rvol still
    rides along because its time-of-day baseline moves with the clock.
    """
    if not new_1m:
        return ChartSeries([], [], [], [], full.rvol)
    first = new_1m[0]
    from_bucket = bucket_start(first, day_map[et_date(first.ts)], TF_MINUTES[tf])
    return ChartSeries(
        bars=[b for b in full.bars if b.ts >= from_bucket],
        vwap=[p for p in full.vwap if p[0] >= first.ts],
        ema9=[p for p in full.ema9 if p[0] >= from_bucket],
        ema20=[p for p in full.ema20 if p[0] >= from_bucket],
        rvol=full.rvol,
    )


def series_json(s: ChartSeries) -> dict:
    return {
        "bars": [bar_json(b) for b in s.bars],
        "overlays": {
            "vwap": point_json(s.vwap),
            "ema9": point_json(s.ema9),
            "ema20": point_json(s.ema20),
        },
        "rvol": s.rvol,
    }
