"""AlpacaProvider against a mock HTTP transport: pagination, the recent-data
clamp, retry/backoff, calendar parsing, key validation."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.providers.alpaca import RECENT_DATA_CLAMP, AlpacaProvider
from app.providers.base import ProviderError

NOW = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)


def make_provider(handler, *, now=NOW):
    sleeps: list[float] = []
    provider = AlpacaProvider(
        "key",
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        now_fn=lambda: now,
    )
    return provider, sleeps


def _bar_json(ts: str, px: float = 100.0) -> dict:
    return {"t": ts, "o": px, "h": px + 1, "l": px - 1, "c": px + 0.5, "v": 1234}


def test_bars_pagination_merges_pages_in_order():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page_token"):
            return httpx.Response(
                200,
                json={"bars": {"SPY": [_bar_json("2026-06-16T13:31:00Z", 101)]}, "next_page_token": None},
            )
        return httpx.Response(
            200,
            json={"bars": {"SPY": [_bar_json("2026-06-16T13:30:00Z", 100)]}, "next_page_token": "TOK"},
        )

    provider, _ = make_provider(handler)
    out = provider.get_bars_1m(
        ["SPY"],
        datetime(2026, 6, 16, 8, 0, tzinfo=UTC),
        datetime(2026, 6, 16, 23, 0, tzinfo=UTC),
    )
    assert len(requests) == 2
    assert requests[1].url.params["page_token"] == "TOK"
    bars = out["SPY"]
    assert [b.ts.minute for b in bars] == [30, 31]
    assert bars[0].open == 100 and bars[1].open == 101
    assert requests[0].url.params["feed"] == "sip"
    assert requests[0].url.params["adjustment"] == "split"


def test_recent_data_clamp_applied_to_end():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"bars": {"SPY": []}, "next_page_token": None})

    provider, _ = make_provider(handler)
    provider.get_bars_1m(["SPY"], NOW - timedelta(hours=6), NOW)  # end = "now"
    sent_end = datetime.fromisoformat(requests[0].url.params["end"])
    assert sent_end == NOW - RECENT_DATA_CLAMP


def test_start_at_or_past_clamped_end_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call expected")

    provider, _ = make_provider(handler)
    out = provider.get_bars_1m(["SPY", "QQQ"], NOW - timedelta(minutes=5), NOW)
    assert out == {"SPY": [], "QQQ": []}


def test_retry_on_429_then_success():
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"bars": {"SPY": []}, "next_page_token": None})

    provider, sleeps = make_provider(handler)
    provider.get_bars_1m(["SPY"], NOW - timedelta(hours=6), NOW - timedelta(hours=1))
    assert len(attempts) == 2
    assert sleeps == [0.0]


def test_forbidden_is_not_retried():
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(403, json={"message": "subscription does not permit"})

    provider, sleeps = make_provider(handler)
    with pytest.raises(ProviderError) as exc:
        provider.get_bars_1m(["SPY"], NOW - timedelta(hours=6), NOW - timedelta(hours=1))
    assert exc.value.status == 403
    assert len(attempts) == 1 and sleeps == []


def test_calendar_parses_compact_and_colon_times():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "paper-api.alpaca.markets"
        return httpx.Response(
            200,
            json=[
                {"date": "2026-11-27", "open": "09:30", "close": "13:00",
                 "session_open": "0400", "session_close": "2000"},
                {"date": "2026-11-30", "open": "09:30", "close": "16:00"},
            ],
        )

    provider, _ = make_provider(handler)
    days = provider.get_calendar(date(2026, 11, 27), date(2026, 11, 30))
    assert days[0].session_open_et == "04:00" and days[0].session_close_et == "20:00"
    assert days[0].is_half_day
    assert days[1].session_open_et == "04:00"  # defaults applied
    assert not days[1].is_half_day


def test_daily_bars_map_to_et_dates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"bars": {"SPY": [_bar_json("2026-06-16T04:00:00Z", 500)]}, "next_page_token": None},
        )

    provider, _ = make_provider(handler)
    out = provider.get_bars_daily(["SPY"], date(2026, 6, 15), date(2026, 6, 16))
    assert out["SPY"][0].day == date(2026, 6, 16)  # 04:00Z = midnight ET


def test_validate_keys_reports_per_host():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "data.alpaca.markets":
            return httpx.Response(200, json={"bars": {}, "next_page_token": None})
        return httpx.Response(401, json={"message": "unauthorized"})

    provider, _ = make_provider(handler)
    v = provider.validate_keys()
    assert v.data_ok and not v.trading_ok and not v.ok
    assert "trading host" in (v.error or "")
