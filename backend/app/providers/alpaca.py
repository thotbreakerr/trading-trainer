"""Alpaca Market Data over raw REST (httpx). ALL external I/O lives here.

Free-tier facts this code depends on (doc §3):
- Recent SIP data is forbidden for ~15 minutes -> every bars request has its
  end clamped to now-16min. A 403 mentioning recent data is a clamp bug here,
  never something to retry.
- Historical bars use feed=sip (full-market volume, correct OHLC) and
  adjustment=split.
"""
from __future__ import annotations

import time as _time
from datetime import UTC, date, datetime, time, timedelta
from typing import Callable, Sequence

import httpx

from app.models import (
    ET,
    CalendarDay,
    DailyBar,
    KeyValidation,
    RawBar,
    et_date,
    utcnow,
)
from app.providers.base import ProviderError

DATA_HOST = "https://data.alpaca.markets"
TRADING_HOST = "https://paper-api.alpaca.markets"

RECENT_DATA_CLAMP = timedelta(minutes=16)  # 15-min rule + 1 min of margin
PAGE_LIMIT = 10_000
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 2.0, 4.0)


def _rfc3339(ts: datetime) -> str:
    return ts.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def _hhmm(raw: str, default: str) -> str:
    """Calendar times arrive as '0400' or '04:00' depending on field."""
    if not raw:
        return default
    return raw if ":" in raw else f"{raw[:2]}:{raw[2:]}"


class AlpacaProvider:
    """Implements app.providers.base.MarketDataProvider."""

    def __init__(
        self,
        key_id: str,
        secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = _time.sleep,
        now_fn: Callable[[], datetime] = utcnow,
    ):
        self._client = httpx.Client(
            headers={
                "APCA-API-KEY-ID": key_id,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
            timeout=30.0,
            transport=transport,
        )
        self._sleep = sleep
        self._now = now_fn

    # ------------------------------------------------------------- internals

    def _get(self, url: str, params: dict) -> dict:
        last: httpx.Response | None = None
        for attempt in range(MAX_ATTEMPTS):
            resp = self._client.get(url, params=params)
            if resp.status_code < 400:
                return resp.json()
            last = resp
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
                self._sleep(delay)
                continue
            break  # other 4xx: not retryable
        assert last is not None
        raise ProviderError(
            f"Alpaca {last.status_code} for {url}: {last.text[:300]}",
            status=last.status_code,
        )

    def _clamp_end(self, end: datetime) -> datetime:
        return min(end, self._now() - RECENT_DATA_CLAMP)

    def _paged_bars(self, params: dict) -> dict[str, list[dict]]:
        merged: dict[str, list[dict]] = {}
        token: str | None = None
        while True:
            page = dict(params)
            if token:
                page["page_token"] = token
            data = self._get(f"{DATA_HOST}/v2/stocks/bars", page)
            for sym, rows in (data.get("bars") or {}).items():
                merged.setdefault(sym, []).extend(rows or [])
            token = data.get("next_page_token")
            if not token:
                return merged

    # ------------------------------------------------- MarketDataProvider API

    def get_bars_1m(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> dict[str, list[RawBar]]:
        out: dict[str, list[RawBar]] = {s: [] for s in symbols}
        end = self._clamp_end(end)
        if not symbols or start >= end:
            return out
        raw = self._paged_bars(
            {
                "symbols": ",".join(symbols),
                "timeframe": "1Min",
                "start": _rfc3339(start),
                "end": _rfc3339(end),
                "limit": PAGE_LIMIT,
                "adjustment": "split",
                "feed": "sip",
                "sort": "asc",
            }
        )
        for sym, rows in raw.items():
            if sym in out:
                out[sym] = [
                    RawBar(
                        ts=_parse_ts(r["t"]),
                        open=float(r["o"]),
                        high=float(r["h"]),
                        low=float(r["l"]),
                        close=float(r["c"]),
                        volume=int(r["v"]),
                    )
                    for r in rows
                ]
        return out

    def get_bars_daily(
        self, symbols: Sequence[str], start: date, end: date
    ) -> dict[str, list[DailyBar]]:
        out: dict[str, list[DailyBar]] = {s: [] for s in symbols}
        if not symbols:
            return out
        # End of the last requested ET day, clamped away from the recent window
        # (today's still-forming daily bar is never needed — 1m data covers it).
        end_ts = self._clamp_end(
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=ET).astimezone(UTC)
        )
        start_ts = datetime.combine(start, time.min, tzinfo=ET).astimezone(UTC)
        if start_ts >= end_ts:
            return out
        raw = self._paged_bars(
            {
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "start": _rfc3339(start_ts),
                "end": _rfc3339(end_ts),
                "limit": PAGE_LIMIT,
                "adjustment": "split",
                "feed": "sip",
                "sort": "asc",
            }
        )
        for sym, rows in raw.items():
            if sym in out:
                out[sym] = [
                    DailyBar(
                        symbol=sym,
                        day=et_date(_parse_ts(r["t"])),
                        open=float(r["o"]),
                        high=float(r["h"]),
                        low=float(r["l"]),
                        close=float(r["c"]),
                        volume=int(r["v"]),
                    )
                    for r in rows
                ]
        return out

    def get_calendar(self, start: date, end: date) -> list[CalendarDay]:
        rows = self._get(
            f"{TRADING_HOST}/v2/calendar",
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        return [
            CalendarDay(
                day=date.fromisoformat(r["date"]),
                open_et=_hhmm(r.get("open", ""), "09:30"),
                close_et=_hhmm(r.get("close", ""), "16:00"),
                session_open_et=_hhmm(r.get("session_open", ""), "04:00"),
                session_close_et=_hhmm(r.get("session_close", ""), "20:00"),
            )
            for r in rows
        ]

    def validate_keys(self) -> KeyValidation:
        data_ok = trading_ok = False
        errors: list[str] = []
        today = self._now().date()
        try:
            self._get(
                f"{DATA_HOST}/v2/stocks/bars",
                {
                    "symbols": "SPY",
                    "timeframe": "1Day",
                    "start": (today - timedelta(days=10)).isoformat(),
                    "end": _rfc3339(self._now() - RECENT_DATA_CLAMP),
                    "limit": 1,
                    "adjustment": "split",
                    "feed": "sip",
                },
            )
            data_ok = True
        except (ProviderError, httpx.HTTPError) as e:
            errors.append(f"data host: {e}")
        try:
            d = today.isoformat()
            self._get(f"{TRADING_HOST}/v2/calendar", {"start": d, "end": d})
            trading_ok = True
        except (ProviderError, httpx.HTTPError) as e:
            errors.append(f"trading host: {e}")
        return KeyValidation(data_ok=data_ok, trading_ok=trading_ok, error="; ".join(errors) or None)
