from datetime import UTC, date, datetime

import pytest

from app.marketdata import store
from app.marketdata.calendar import (
    STATE_CLOSED,
    STATE_OPEN,
    STATE_POST,
    STATE_PRE,
    CalendarUnavailable,
    MarketCalendar,
    tag_session,
)
from app.models import CalendarDay, et_clock_to_utc


def _cd(d: date, close: str = "16:00") -> CalendarDay:
    return CalendarDay(d, "09:30", close, "04:00", "20:00")


# ------------------------------------------------------------- pure helpers


def test_et_clock_to_utc_is_dst_safe():
    # US spring-forward Sunday 2026-03-08: same ET clock, different UTC
    assert et_clock_to_utc(date(2026, 3, 6), "09:30") == datetime(2026, 3, 6, 14, 30, tzinfo=UTC)
    assert et_clock_to_utc(date(2026, 3, 9), "09:30") == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)


def test_tag_session_boundaries_regular_day():
    cal = _cd(date(2026, 6, 16))
    assert tag_session(et_clock_to_utc(cal.day, "09:29"), cal) == "pre"
    assert tag_session(et_clock_to_utc(cal.day, "09:30"), cal) == "rth"
    assert tag_session(et_clock_to_utc(cal.day, "15:59"), cal) == "rth"  # last RTH bar
    assert tag_session(et_clock_to_utc(cal.day, "16:00"), cal) == "post"


def test_tag_session_half_day_reads_calendar_not_hardcoded_times():
    cal = _cd(date(2026, 11, 27), close="13:00")
    assert cal.is_half_day
    assert tag_session(et_clock_to_utc(cal.day, "12:59"), cal) == "rth"
    assert tag_session(et_clock_to_utc(cal.day, "13:00"), cal) == "post"


# ---------------------------------------------------------------- navigation


@pytest.fixture
def cal(conn, cal_days) -> MarketCalendar:
    store.upsert_calendar(conn, cal_days)
    return MarketCalendar(conn)


def test_navigation_skips_weekends_and_holidays(cal):
    assert cal.is_trading_day(date(2026, 6, 16))
    assert not cal.is_trading_day(date(2026, 6, 13))  # Saturday

    assert cal.prev_trading_day(date(2026, 6, 15)).day == date(2026, 6, 12)
    assert cal.next_trading_day(date(2026, 11, 25)).day == date(2026, 11, 27)  # skip Thanksgiving
    assert cal.latest_on_or_before(date(2026, 6, 14)).day == date(2026, 6, 12)

    back = cal.trading_days_back(date(2026, 6, 17), 4)
    assert [c.day.day for c in back] == [12, 15, 16, 17]


def test_trading_days_back_raises_when_history_insufficient(cal):
    with pytest.raises(CalendarUnavailable):
        cal.trading_days_back(date(2026, 3, 6), 10)  # only 2 fixture days exist


def test_ensure_range_without_provider_raises(conn):
    with pytest.raises(CalendarUnavailable):
        MarketCalendar(conn).ensure_range(date(2026, 6, 1), date(2026, 6, 30))


# --------------------------------------------------------------- market state


def _et(d: date, hhmm: str) -> datetime:
    return et_clock_to_utc(d, hhmm)


def test_market_state_weekend_displays_prior_friday(cal):
    st = cal.market_state(_et(date(2026, 6, 13), "12:00"))  # Saturday noon
    assert st.state == STATE_CLOSED
    assert st.display_day == date(2026, 6, 12)


def test_market_state_through_a_trading_day(cal):
    d = date(2026, 6, 16)
    assert cal.market_state(_et(d, "03:00")).state == STATE_CLOSED  # before pre
    assert cal.market_state(_et(d, "03:00")).display_day == date(2026, 6, 15)
    assert cal.market_state(_et(d, "08:00")).state == STATE_PRE
    assert cal.market_state(_et(d, "12:00")).state == STATE_OPEN
    assert cal.market_state(_et(d, "17:00")).state == STATE_POST
    assert cal.market_state(_et(d, "21:00")).state == STATE_CLOSED
    assert cal.market_state(_et(d, "12:00")).display_day == d


def test_market_state_half_day_closes_early(cal):
    d = date(2026, 11, 27)
    assert cal.market_state(_et(d, "12:30")).state == STATE_OPEN
    assert cal.market_state(_et(d, "14:00")).state == STATE_POST  # closed at 13:00 ET
