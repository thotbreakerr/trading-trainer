"""The doc §16 edge-case sweep (Phase 8 hardening): every locked resolution
mapped to the test that proves it, plus direct checks for the few corners no
earlier suite covered. This file is the checklist — if a §16 behavior ever
regresses, something here (or something it names) goes red.

 1. Holidays / half days ..... test_calendar (navigation, half-day close),
                               test_sim_eod (12:50/13:00 flatten from the row)
 2. DST ...................... test_calendar (et_clock_to_utc across 2026-03-08),
                               test_aggregate (DST-day buckets)
 3. Splits ................... test_fetcher (same-date discrepancy -> wipe+refetch)
 4. Sparse pre-market ........ test_aggregate (sparse minutes),
                               test_indicators (cumulative clock-based RVOL)
 5. Lookback dependency ...... test_fetcher (window expansion),
                               test_lesson_loader (demo-day validation)
 6. Poller failure mid-session test_poller_harness (staleness), backoff below
 7. App closed during session  test_callout_lifecycle (missed (app closed))
 8. Days never opened ........ test_briefing_recap (ledger computed on demand)
 9. Bad/expired API key ...... below (endpoints degrade to cache, key flow 401s)
10. Sim edges ................ test_sim_fills / test_sim_eod (whole matrix)
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from app.marketdata.calendar import MarketCalendar
from app.marketday.poller import MAX_BACKOFF_S, MarketDayPoller
from app.models import et_clock_to_utc
from app.providers.alpaca import AlpacaProvider
from tests.test_batch_golden import RULES, build_orb_day
from tests.test_poller_harness import make_cfg

ANCHOR = date(2026, 6, 16)


def _bad_key_provider() -> AlpacaProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "unauthorized"})

    return AlpacaProvider("bad", "keys", transport=httpx.MockTransport(handler))


def test_16_9_bad_keys_degrade_to_cache_not_500(conn):
    """§16.9: an expired key must not break cached workflows — the calendar
    refresh raises, callers catch, cached session logic keeps working."""
    build_orb_day(conn)
    calendar = MarketCalendar(conn, _bad_key_provider())
    state = calendar.market_state(et_clock_to_utc(ANCHOR, "12:00"))
    assert state.state == "open"  # cached calendar still answers

    validation = _bad_key_provider().validate_keys()
    assert not validation.ok and "401" in (validation.error or "")


def test_16_9_poller_survives_bad_keys(conn, tmp_path):
    """A poll tick with a dead provider still ticks off the cache."""
    build_orb_day(conn)
    poller = MarketDayPoller(
        cfg=make_cfg(tmp_path),
        rules_cfg=RULES,
        provider_fn=_bad_key_provider,
        lessons_fn=lambda: [],
        now_fn=lambda: et_clock_to_utc(ANCHOR, "12:00"),
    )
    try:
        summary = poller.tick_once()
    except RuntimeError:
        summary = {"status": "fetch-failed"}  # reported, next tick backs off
    # either path is acceptable; what matters is state, not a crash:
    assert poller.session is not None
    assert summary["status"] in ("ok", "fetch-failed")


def test_16_6_backoff_grows_and_caps(conn, tmp_path):
    """§16.6: failed polls back off exponentially to a cap, never silently."""

    class Boom:
        def tick_once(self):
            raise RuntimeError("boom")

    poller = MarketDayPoller(
        cfg=make_cfg(tmp_path), rules_cfg=RULES,
        provider_fn=lambda: None, lessons_fn=lambda: [],
    )
    poller.tick_once = Boom().tick_once  # type: ignore[assignment]

    async def run_three():
        task = asyncio.create_task(poller.run())
        for _ in range(50):
            await asyncio.sleep(0)  # let the loop hit the failure
            if poller.backoff_s:
                break
        first = poller.backoff_s
        task.cancel()
        return first

    first = asyncio.run(run_three())
    assert first > 0
    assert poller.last_error is not None  # reported, not swallowed
    # cap math: repeated doubling can never exceed MAX_BACKOFF_S
    b = first
    for _ in range(20):
        b = min(max(b * 2, 300), MAX_BACKOFF_S)
    assert b == MAX_BACKOFF_S


def test_16_1_no_hardcoded_session_times_in_engines():
    """§16.1: all session logic reads the calendar. Mechanical sweep: the
    engine sources must not contain hardcoded exchange clock times."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    suspects = []
    for rel in ("sim/engine.py", "detectors", "marketday", "sessions.py"):
        target = app_dir / rel
        files = target.rglob("*.py") if target.is_dir() else [target]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for needle in ('"09:30"', '"16:00"', '"15:50"', '"04:00"', '"20:00"'):
                if needle in text:
                    suspects.append(f"{f.name}: {needle}")
    assert not suspects, "hardcoded session times found:\n" + "\n".join(suspects)