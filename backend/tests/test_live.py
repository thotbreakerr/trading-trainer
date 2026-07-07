"""Live smoke tests against the real Alpaca API (deselected by default).

    python -m pytest -m live

Requires APCA_API_KEY_ID / APCA_API_SECRET_KEY in .env under
%LOCALAPPDATA%/trading-trainer (or in the environment) — these skip cleanly
when keys are absent.
"""
from __future__ import annotations

import pytest

from app import db
from app.config import load_creds
from app.marketdata import store
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher
from app.models import ET, utcnow
from app.providers.alpaca import AlpacaProvider

creds = load_creds()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(creds is None, reason="no Alpaca keys in .env (local data dir)"),
]


@pytest.fixture
def live_conn(tmp_path):
    conn = db.init_db(tmp_path / "live.db")
    yield conn
    db.close_all()


@pytest.fixture
def provider() -> AlpacaProvider:
    assert creds is not None
    return AlpacaProvider(creds.key_id, creds.secret)


def test_validate_keys_against_both_hosts(provider):
    v = provider.validate_keys()
    assert v.ok, v.error


def test_full_spy_day_fetch_with_session_tags(live_conn, provider):
    calendar = MarketCalendar(live_conn, provider)
    fetcher = Fetcher(live_conn, provider, calendar)
    today_et = utcnow().astimezone(ET).date()
    calendar.ensure_around(today_et)
    # Most recent COMPLETE trading day (yesterday-or-earlier, never today).
    target = calendar.prev_trading_day(calendar.latest_on_or_before(today_et).day)

    report = fetcher.ensure_day("SPY", target.day)

    assert report.bars_added > 0
    assert report.daily_bars_added >= 200  # SMA200 context history
    bars = store.get_bars_1m_raw(
        live_conn, "SPY",
        start=target.session_open_utc(),
        end=target.session_close_utc(),
    )
    assert len(bars) > 600  # SPY prints nearly every minute incl. extended
    assert {b.session for b in bars} == {"pre", "rth", "post"}
    rth = [b for b in bars if b.session == "rth"]
    expected_rth = 200 if target.is_half_day else 385
    assert len(rth) >= expected_rth
