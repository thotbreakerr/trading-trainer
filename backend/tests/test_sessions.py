"""Replay session pipeline: hidden start, ordered reveal, determinism,
restart-not-rewind, hard stop at session close (doc §8)."""
from __future__ import annotations

from datetime import date, timedelta

from app import sessions
from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BarWindow
from app.models import CalendarDay, et_clock_to_utc
from tests.conftest import seed_days

ANCHOR = date(2026, 6, 17)


def _days():
    return [
        CalendarDay(date(2026, 6, 15), "09:30", "16:00", "04:00", "20:00"),
        CalendarDay(date(2026, 6, 16), "09:30", "16:00", "04:00", "20:00"),
        CalendarDay(ANCHOR, "09:30", "16:00", "04:00", "20:00"),
    ]


def make(conn):
    seed_days(conn, "SPY", _days())
    calendar = MarketCalendar(conn)
    session = sessions.create_session(calendar, ["SPY"], ANCHOR, lookback_days=2)
    window = BarWindow(conn, calendar, session.clock, ANCHOR, lookback_days=2)
    return session, window


def test_create_starts_at_open_with_rth_hidden(conn):
    session, _ = make(conn)
    assert session.clock.current == et_clock_to_utc(ANCHOR, "09:30")
    assert not session.done


def test_step_reveals_bars_in_order(conn):
    session, window = make(conn)
    r1 = sessions.step_session(session, window, 1)
    assert [b.ts for b in r1.new_bars["SPY"]] == [et_clock_to_utc(ANCHOR, "09:30")]
    r2 = sessions.step_session(session, window, 2)
    assert [b.ts for b in r2.new_bars["SPY"]] == [
        et_clock_to_utc(ANCHOR, "09:31"),
        et_clock_to_utc(ANCHOR, "09:32"),
    ]
    assert session.clock.current == et_clock_to_utc(ANCHOR, "09:33")


def test_two_sessions_same_day_are_identical(conn):
    session_a, window_a = make(conn)
    calendar = MarketCalendar(conn)
    session_b = sessions.create_session(calendar, ["SPY"], ANCHOR, lookback_days=2)
    window_b = BarWindow(conn, calendar, session_b.clock, ANCHOR, lookback_days=2)

    def run(session, window):
        stream = []
        for n in (1, 3, 5, 2):
            result = sessions.step_session(session, window, n)
            stream += [(b.ts, b.close) for b in result.new_bars["SPY"]]
        return stream

    assert run(session_a, window_a) == run(session_b, window_b)


def test_restart_resets_to_hidden_day(conn):
    session, window = make(conn)
    sessions.step_session(session, window, 10)
    sessions.restart_session(session)
    assert session.clock.current == session.start_at
    r = sessions.step_session(session, window, 1)
    assert [b.ts for b in r.new_bars["SPY"]] == [et_clock_to_utc(ANCHOR, "09:30")]


def test_step_never_passes_session_close(conn):
    session, window = make(conn)
    guard = 0
    last_result = None
    while not session.done:
        last_result = sessions.step_session(session, window, 60)
        guard += 1
        assert guard < 30, "session never finished"
    assert session.clock.current == session.end_at
    assert last_result is not None
    all_final = sessions.step_session(session, window, 60)  # step after done
    assert all_final.done and all_final.new_bars["SPY"] == []
    assert session.clock.current == session.end_at  # clock pinned at close


def test_step_size_is_capped(conn):
    session, window = make(conn)
    sessions.step_session(session, window, 500)
    assert session.clock.current == session.start_at + timedelta(minutes=sessions.MAX_STEP_BARS)