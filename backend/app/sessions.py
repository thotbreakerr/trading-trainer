"""Replay sessions: registry + the step pipeline.

This pipeline is the code path Market Day will later drive too (doc §11:
"delayed-live is just the replay engine fed by a poller") — the sim and
callout engines plug into the step loop in later phases.

Sessions hold NO database connection: sqlite connections are thread-local
and FastAPI serves each request on an arbitrary threadpool thread, so
endpoints construct a per-request BarWindow bound to the session's clock.

Visibility recap (doc §8): the clock starts at the anchor day's open, so the
cutoff sits one bar earlier — prior days and the anchor's pre-market are
context, the anchor's RTH is hidden and reveals bar by bar. Whole 1-minute
bars only; step = +60s per bar.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from app.marketdata.calendar import MarketCalendar
from app.marketdata.window import BAR_SECONDS, BarWindow, Clock, ReplayClock
from app.models import Bar, CalendarDay
from app.sim.engine import SimEngine

MAX_STEP_BARS = 60


class SessionNotFound(KeyError):
    pass


@dataclass
class LessonCtx:
    """Which lesson step owns this session — and, for graded practice, the
    best entry grade earned so far (server-side, never client-claimed)."""

    module: int
    step: int
    require_grade: str | None = None
    best_grade: str | None = None


@dataclass
class Session:
    id: str
    mode: str  # 'replay' | 'lesson' | 'review' | 'marketday'
    symbols: list[str]
    day: date
    cal_day: CalendarDay
    lookback_days: int
    clock: Clock  # ReplayClock, or DelayedLiveClock for Market Day
    start_at: datetime
    end_at: datetime  # anchor session close — the step loop stops here
    last_seen: dict[str, datetime]  # per-symbol high-water mark (a TIME, not a bar)
    sim: SimEngine | None = None
    lesson_ctx: LessonCtx | None = None
    persisted_trades: int = 0  # journal write-through high-water mark
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def done(self) -> bool:
        return self.clock.now() >= self.end_at


@dataclass
class StepResult:
    clock: datetime
    cutoff: datetime
    done: bool
    new_bars: dict[str, list[Bar]]
    events: list[dict]  # sim fills/rejects/EOD now; callouts join later


_SESSIONS: dict[str, Session] = {}
_REGISTRY_LOCK = threading.Lock()


def create_session(
    calendar: MarketCalendar,
    symbols: list[str],
    day: date,
    *,
    lookback_days: int = 3,
    start: str = "open",  # 'open' | 'session_open'
    start_at: datetime | None = None,  # review mode: jump straight to a moment
    mode: str = "replay",
    sim: SimEngine | None = None,
    lesson_ctx: LessonCtx | None = None,
    clock: Clock | None = None,  # Market Day passes a DelayedLiveClock
) -> Session:
    cal_day = calendar.day(day)
    if cal_day is None:
        raise ValueError(f"{day} is not a trading day")
    if start_at is None:
        start_at = cal_day.open_utc() if start == "open" else cal_day.session_open_utc()
    initial_cutoff = start_at - timedelta(seconds=BAR_SECONDS)
    session = Session(
        id=uuid.uuid4().hex[:12],
        mode=mode,
        symbols=[s.upper() for s in symbols],
        day=day,
        cal_day=cal_day,
        lookback_days=lookback_days,
        clock=clock if clock is not None else ReplayClock(current=start_at),
        start_at=start_at,
        end_at=cal_day.session_close_utc(),
        last_seen={s.upper(): initial_cutoff for s in symbols},
        sim=sim,
        lesson_ctx=lesson_ctx,
    )
    with _REGISTRY_LOCK:
        _SESSIONS[session.id] = session
    return session


def get_session(session_id: str) -> Session:
    with _REGISTRY_LOCK:
        session = _SESSIONS.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)
    return session


def delete_session(session_id: str) -> None:
    with _REGISTRY_LOCK:
        _SESSIONS.pop(session_id, None)


def _reveal_and_process(session: Session, window: BarWindow) -> StepResult:
    """The shared pipeline: reveal newly visible bars, feed the sim, run EOD
    checks. Replay calls it after advancing the clock; the Market Day poller
    calls it as-is — the clock advances by itself (doc §11)."""
    cutoff = window.cutoff()
    new_bars: dict[str, list[Bar]] = {}
    events: list[dict] = []
    for symbol in session.symbols:
        since = session.last_seen[symbol] + timedelta(seconds=BAR_SECONDS)
        revealed = window.bars_1m(symbol, since=since) if since <= cutoff else []
        new_bars[symbol] = revealed
        session.last_seen[symbol] = max(cutoff, session.last_seen[symbol])
        if session.sim is not None:
            for bar in revealed:
                events += [e.to_json() for e in session.sim.on_bar(bar)]
    if session.sim is not None:
        events += [
            e.to_json() for e in session.sim.on_clock(session.clock.now(), session.cal_day)
        ]
    return StepResult(
        clock=session.clock.now(),
        cutoff=cutoff,
        done=session.done,
        new_bars=new_bars,
        events=events,
    )


def step_session(session: Session, window: BarWindow, bars: int = 1) -> StepResult:
    """Advance the clock N whole bars and reveal exactly what became visible.
    Deterministic: same day + same steps => identical bar streams."""
    bars = max(1, min(bars, MAX_STEP_BARS))
    with session.lock:
        assert isinstance(session.clock, ReplayClock), "only replay clocks can be stepped"
        if not session.done:
            session.clock.current = min(
                session.clock.current + timedelta(seconds=BAR_SECONDS * bars),
                session.end_at,
            )
        return _reveal_and_process(session, window)


def tick_session(session: Session, window: BarWindow) -> StepResult:
    """Delayed-live tick: no clock math here — wall time already moved."""
    with session.lock:
        return _reveal_and_process(session, window)


def restart_session(session: Session) -> None:
    """Practice rule (doc §8): no rewind — restart the day, fresh."""
    with session.lock:
        assert isinstance(session.clock, ReplayClock), "only replay sessions restart"
        session.clock.current = session.start_at
        initial_cutoff = session.start_at - timedelta(seconds=BAR_SECONDS)
        session.last_seen = {s: initial_cutoff for s in session.symbols}


def seek_session(session: Session, to_epoch: int) -> None:
    """Lesson-only navigation: everything derives from the clock, so setting
    it (and resetting the high-water marks) is a complete state change."""
    target = datetime.fromtimestamp(to_epoch, tz=UTC)
    target = max(session.start_at, min(target, session.end_at))
    with session.lock:
        assert isinstance(session.clock, ReplayClock), "only replay sessions seek"
        session.clock.current = target
        cutoff = target - timedelta(seconds=BAR_SECONDS)
        session.last_seen = {s: cutoff for s in session.symbols}
