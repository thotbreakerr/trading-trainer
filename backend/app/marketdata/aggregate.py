"""Pure timeframe aggregation: 5m/15m/hourly derived on the fly from stored
1-minute bars (doc §5) — nothing coarser than 1m intraday is ever stored.

Bucketing rules:
- Buckets anchor at each session segment's start (pre: extended open, RTH:
  the bell, post: the close) and NEVER cross segment boundaries — a 09:30
  bucket must not swallow 09:29 pre-market prints, and RTH hourly candles
  run 09:30-10:30-... like traders expect. Half days clip naturally because
  segment bounds come from the calendar row.
- A bucket's bar: first open, max high, min low, last close, summed volume,
  the segment's session tag, ts = bucket start.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Mapping, Sequence

from app.models import SESSION_PRE, SESSION_RTH, Bar, CalendarDay, et_date

TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def _segment_start(bar: Bar, cal: CalendarDay):
    if bar.session == SESSION_PRE:
        return cal.session_open_utc()
    if bar.session == SESSION_RTH:
        return cal.open_utc()
    return cal.close_utc()


def bucket_start(bar: Bar, cal: CalendarDay, tf_minutes: int) -> datetime:
    """Start of the tf bucket this 1m bar falls into (segment-anchored).

    Monotone non-decreasing in bar.ts within a day: segment anchors are
    ordered and buckets never cross them — which is what makes a trailing
    slice at one bucket boundary exactly the set of buckets a step touched.
    """
    if tf_minutes == 1:
        return bar.ts
    seg = _segment_start(bar, cal)
    width = timedelta(minutes=tf_minutes)
    return seg + ((bar.ts - seg) // width) * width


def aggregate_bars(
    bars: Sequence[Bar], tf_minutes: int, days: Mapping[date, CalendarDay]
) -> list[Bar]:
    """Aggregate 1m bars (any symbols, ascending ts) into tf_minutes buckets.
    `days` must contain a CalendarDay for every ET date present in `bars`."""
    if tf_minutes == 1:
        return list(bars)
    out: dict[tuple, Bar] = {}
    order: list[tuple] = []
    for bar in bars:
        day = et_date(bar.ts)
        cal = days.get(day)
        if cal is None:
            raise ValueError(f"no calendar day supplied for {bar.symbol} bar on {day}")
        bucket_ts = bucket_start(bar, cal, tf_minutes)
        key = (bar.symbol, bucket_ts, bar.session)
        cur = out.get(key)
        if cur is None:
            out[key] = Bar(
                symbol=bar.symbol,
                ts=bucket_ts,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                session=bar.session,
            )
            order.append(key)
        else:
            out[key] = Bar(
                symbol=cur.symbol,
                ts=cur.ts,
                open=cur.open,
                high=max(cur.high, bar.high),
                low=min(cur.low, bar.low),
                close=bar.close,
                volume=cur.volume + bar.volume,
                session=cur.session,
            )
    return sorted((out[k] for k in order), key=lambda b: (b.symbol, b.ts))
