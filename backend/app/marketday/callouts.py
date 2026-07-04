"""Callout lifecycle (doc §11): Fired -> Watching (countdown) -> exactly one
of acted / invalidated / expired — then hindsight-tracked to its natural
outcome. Locked concepts still fire (the ledger needs them) but present as
teaser cards; the coach only SPEAKS for what you've unlocked (doc §10/§12)."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.detectors.engine import REGISTRY, live_signals
from app.detectors.types import Signal
from app.grading.grader import GradeResult, grade_signal
from app.marketday.hindsight import track_outcome
from app.marketdata.window import BarWindow, RvolBaseline
from app.models import et_date, to_db_ts
from app.stores import setups as setups_store

UNLOCK_KEY_BY_PREFIX = {name: unlock for name, _fn, _cfg, unlock in REGISTRY}


def _unlock_key(signal: Signal) -> str:
    if signal.setup_type.startswith("level_break"):
        return "level_break"
    if signal.setup_type in ("gap_up", "gap_down"):
        return "gap_context"
    if signal.setup_type == "gap_fill":
        return "gap_fill"
    if signal.setup_type in ("orb_long", "orb_short"):
        return "opening_range_breakout"
    if signal.setup_type in ("vwap_reclaim", "vwap_loss"):
        return "vwap_reclaim"
    if signal.setup_type == "vwap_pullback":
        return "vwap_pullback"
    if signal.setup_type == "rvol_spike":
        return "rvol_spike"
    return "trend_state"


@dataclass
class Callout:
    id: str
    signal: Signal
    grade: GradeResult | None
    fired_at: datetime  # clock time when it appeared
    watch_until: datetime
    locked: bool
    unlock_module: int | None
    setup_row_id: int | None = None
    status: str = "watching"  # watching | acted | invalidated | expired
    invalidated_reason: str | None = None
    outcome: str | None = None
    outcome_r: float | None = None

    @property
    def tradeable(self) -> bool:
        return self.signal.entry is not None and self.signal.stop is not None

    def to_json(self, clock: datetime) -> dict:
        if self.locked:
            # teaser only: "*Something* fired at 9:47 — unlocks in Module N"
            return {
                "id": self.id,
                "locked": True,
                "symbol": self.signal.symbol,
                "fired_ts": to_db_ts(self.signal.ts),
                "unlock_module": self.unlock_module,
                "status": self.status,
            }
        return {
            "id": self.id,
            "locked": False,
            "symbol": self.signal.symbol,
            "setup_type": self.signal.setup_type,
            "direction": self.signal.direction,
            "entry": self.signal.entry,
            "stop": self.signal.stop,
            "target": self.signal.target,
            "rr": self.signal.rr,
            "context": self.signal.context,
            "fired_ts": to_db_ts(self.signal.ts),
            "grade": self.grade.to_json() if self.grade else None,
            "status": self.status,
            "watch_seconds_left": max(0, int((self.watch_until - clock).total_seconds()))
            if self.status == "watching"
            else 0,
            "invalidated_reason": self.invalidated_reason,
            "outcome": self.outcome,
            "outcome_r": self.outcome_r,
            "tradeable": self.tradeable,
        }


@dataclass
class CalloutEngine:
    rules_cfg: dict
    unlocked: set[str]
    mode: str = "marketday"
    fired_keys: set = field(default_factory=set)
    callouts: dict[str, Callout] = field(default_factory=dict)

    def _watch_minutes(self, setup_type: str) -> int:
        cfg = self.rules_cfg.get("callouts", {}) or {}
        per_setup = cfg.get("watch_minutes", {}) or {}
        return int(per_setup.get(setup_type, cfg.get("default_watch_minutes", 10)))

    def on_tick(
        self,
        conn: sqlite3.Connection,
        window: BarWindow,
        symbols: list[str],
        day: date,
        rvol_baselines: dict[str, RvolBaseline | None] | None = None,
    ) -> list[dict]:
        """Detect new fires, advance the state machine, track hindsight.
        Returns UI events."""
        clock = window.clock.now()
        events: list[dict] = []
        from app.detectors.engine import build_snapshot  # local: avoid cycle

        snapshots = {}
        for symbol in symbols:
            baseline = (rvol_baselines or {}).get(symbol)
            snap = build_snapshot(window, symbol, rvol_baseline=baseline)
            snapshots[symbol] = snap
            # detectors compute EVERYTHING; unlock gating is presentation-side
            for signal in live_signals(
                window, symbol, self.rules_cfg, self.fired_keys, unlocked=None,
                rvol_baseline=baseline,
            ):
                events += self._fire(conn, signal, snap, day, clock)
        events += self._advance(conn, window, clock)
        return events

    def _fire(self, conn, signal: Signal, snap, day: date, clock: datetime) -> list[dict]:
        unlock_key = _unlock_key(signal)
        locked = unlock_key not in self.unlocked
        grade = grade_signal(signal, snap, self.rules_cfg.get("grading", {}))
        minutes = self._watch_minutes(signal.setup_type)
        watch_until = clock + timedelta(minutes=minutes)
        callout = Callout(
            id=uuid.uuid4().hex[:10],
            signal=signal,
            grade=grade,
            fired_at=clock,
            watch_until=watch_until,
            locked=locked,
            unlock_module=(self.rules_cfg.get("unlocks", {}) or {}).get(unlock_key),
        )
        # App-closed catch-up: a fire discovered long after its bar is already
        # history — straight to the ledger, marked (doc §16.7).
        missed = clock - signal.ts > timedelta(minutes=minutes)
        note = "missed (app closed)" if missed else None
        if missed:
            callout.status = "expired"
        callout.setup_row_id = setups_store.insert_setup(
            conn, day=day, signal=signal, grade=grade,
            status=callout.status, mode=self.mode, note=note,
        )
        self.callouts[callout.id] = callout
        return [{"kind": "callout_fired", "callout": callout.to_json(clock),
                 "sound": not locked and not missed}]

    def _advance(self, conn, window: BarWindow, clock: datetime) -> list[dict]:
        events: list[dict] = []
        for callout in self.callouts.values():
            if callout.status == "watching":
                events += self._check_watching(conn, callout, window, clock)
            if callout.status in ("invalidated", "expired", "acted") and callout.outcome is None:
                self._track_hindsight(conn, callout, window)
        return events

    def _check_watching(self, conn, callout: Callout, window: BarWindow, clock) -> list[dict]:
        sig = callout.signal
        if callout.tradeable:
            bars = [
                b for b in window.bars_1m(sig.symbol, since=sig.ts)
                if et_date(b.ts) == window.anchor.day
            ]
            for bar in bars:
                stopped = (
                    bar.low <= sig.stop if sig.direction == "long" else bar.high >= sig.stop
                )
                if stopped:
                    callout.status = "invalidated"
                    callout.invalidated_reason = (
                        f"failed {sig.setup_type.replace('_', ' ')} — price broke the "
                        f"stop level {sig.stop:.2f} before the move went anywhere. "
                        "That was the trap side of this trade."
                    )
                    if callout.setup_row_id:
                        setups_store.update_status(
                            conn, callout.setup_row_id, "invalidated", callout.invalidated_reason
                        )
                    return [{"kind": "callout_invalidated", "callout": callout.to_json(clock)}]
        if clock >= callout.watch_until:
            callout.status = "expired"
            if callout.setup_row_id:
                setups_store.update_status(conn, callout.setup_row_id, "expired")
            return [{"kind": "callout_expired", "callout": callout.to_json(clock)}]
        return []

    def _track_hindsight(self, conn, callout: Callout, window: BarWindow) -> None:
        sig = callout.signal
        if not callout.tradeable or sig.target is None:
            callout.outcome = "n/a"
            return
        bars = [
            b for b in window.bars_1m(sig.symbol, since=sig.ts)
            if et_date(b.ts) == window.anchor.day
        ]
        # only conclude at day end or once a terminal outcome exists
        result = track_outcome(bars, sig.direction, sig.entry, sig.stop, sig.target)
        day_over = window.clock.now() >= window.anchor.close_utc()
        if result.outcome in ("target", "stop") or day_over:
            callout.outcome = result.outcome
            callout.outcome_r = result.r_multiple
            if callout.setup_row_id:
                setups_store.record_outcome(
                    conn, callout.setup_row_id, result.outcome, result.r_multiple
                )

    def mark_acted(self, conn, callout: Callout, ts, user_grade: GradeResult) -> None:
        import json

        callout.status = "acted"
        if callout.setup_row_id:
            setups_store.record_user_action(
                conn, callout.setup_row_id, ts, user_grade.tier,
                json.dumps(user_grade.to_json()["checklist"]),
            )

    def visible(self, clock: datetime) -> list[dict]:
        return [c.to_json(clock) for c in sorted(
            self.callouts.values(), key=lambda c: c.fired_at, reverse=True
        )]
