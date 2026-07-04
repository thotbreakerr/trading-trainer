"""Paper-trading sim (doc §9). Worst-case bias everywhere:

- Market orders fill at the NEXT bar's open — never the price you clicked.
- Limits fill when a bar trades through; gapped through -> the bar's open.
- Stops trigger on high/low cross; fill at stop, or the open if gapped past.
- A bar that touches both stop and target: the STOP is assumed to have
  fired first.
- Whole fills only, one position per symbol, 4x intraday buying power with
  clean rejects, EOD warn + forced flatten at the close (half days included —
  times come from the calendar row, never hardcoded).

The engine is deliberately I/O-free: the session step pipeline feeds it
revealed bars in timestamp order and persists its events afterwards.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.models import Bar, CalendarDay, to_db_ts

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop"]
Role = Literal["standalone", "entry", "stop", "target", "exit"]

EOD_WARN_MINUTES = 10  # warn this long before the close (15:50 on full days)


class OrderError(ValueError):
    pass


@dataclass
class SimOrder:
    id: int
    symbol: str
    side: Side
    type: OrderType
    qty: int
    limit_price: float | None = None
    stop_price: float | None = None
    bracket_id: str | None = None
    role: Role = "standalone"
    status: str = "working"  # working | pending (exit awaiting entry) | filled | canceled | rejected
    placed_ts: datetime | None = None
    filled_ts: datetime | None = None
    fill_price: float | None = None
    reason: str | None = None
    setup_id: int | None = None


@dataclass
class Position:
    symbol: str
    qty: int  # signed: + long, - short
    avg_price: float
    entry_ts: datetime
    initial_stop: float | None  # defines 1R for the journal
    entry_order_id: int
    setup_id: int | None = None


@dataclass
class Trade:
    id: int
    symbol: str
    direction: str  # long | short
    qty: int
    entry_ts: datetime
    entry_price: float
    stop_price: float | None
    exit_ts: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None  # target | stop | manual | eod
    r_multiple: float | None = None
    setup_id: int | None = None
    grade: str | None = None  # entry grade at decision time (doc §10)

    @property
    def closed(self) -> bool:
        return self.exit_ts is not None


@dataclass
class SimEvent:
    kind: str  # fill | reject | cancel | eod_warning | eod_flatten
    ts: datetime
    symbol: str | None = None
    order_id: int | None = None
    detail: str = ""

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "ts": to_db_ts(self.ts),
            "symbol": self.symbol,
            "order_id": self.order_id,
            "detail": self.detail,
        }


@dataclass
class SimEngine:
    starting_balance: float
    leverage: float = 4.0
    mode: str = "practice"

    cash: float = field(init=False)
    orders: dict[int, SimOrder] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    last_close: dict[str, float] = field(default_factory=dict)
    # entry grade parked at placement, claimed by the entry fill (per symbol)
    pending_grades: dict[str, str] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _bracket_ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _eod_warned: bool = False
    flattened: bool = False

    def __post_init__(self) -> None:
        self.cash = self.starting_balance

    # ------------------------------------------------------------- accounting

    def equity(self) -> float:
        value = self.cash
        for pos in self.positions.values():
            price = self.last_close.get(pos.symbol, pos.avg_price)
            value += pos.qty * price
        return value

    def exposure(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            price = self.last_close.get(pos.symbol, pos.avg_price)
            total += abs(pos.qty) * price
        for order in self.orders.values():
            if order.status == "working" and order.role in ("standalone", "entry"):
                ref = order.limit_price or order.stop_price or self.last_close.get(order.symbol, 0.0)
                total += order.qty * ref
        return total

    def buying_power_left(self) -> float:
        return self.equity() * self.leverage - self.exposure()

    # -------------------------------------------------------------- placement

    def _next_id(self) -> int:
        return next(self._ids)

    def _reject(self, order: SimOrder, ts: datetime, reason: str) -> list[SimEvent]:
        order.status = "rejected"
        order.reason = reason
        self.orders[order.id] = order
        return [SimEvent("reject", ts, order.symbol, order.id, reason)]

    def _entry_ref_price(self, order: SimOrder) -> float:
        return (
            order.limit_price
            or order.stop_price
            or self.last_close.get(order.symbol, 0.0)
        )

    def place_order(
        self,
        ts: datetime,
        symbol: str,
        side: Side,
        type: OrderType,
        qty: int,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> tuple[SimOrder, list[SimEvent]]:
        symbol = symbol.upper()
        order = SimOrder(
            id=self._next_id(), symbol=symbol, side=side, type=type,
            qty=qty, limit_price=limit_price, stop_price=stop_price, placed_ts=ts,
        )
        position = self.positions.get(symbol)
        closing = position is not None and (
            (position.qty > 0 and side == "sell") or (position.qty < 0 and side == "buy")
        )
        if closing:
            assert position is not None
            if qty != abs(position.qty):
                return order, self._reject(
                    order, ts,
                    f"whole fills only — close all {abs(position.qty)} shares",
                )
            order.role = "exit"
        events = self._validate_entry(order, ts, opens_position=not closing)
        if not events:
            self.orders[order.id] = order
        return order, events

    def place_bracket(
        self,
        ts: datetime,
        symbol: str,
        side: Side,
        qty: int,
        stop_price: float,
        target_price: float,
        entry_type: OrderType = "market",
        limit_price: float | None = None,
        setup_id: int | None = None,
    ) -> tuple[list[SimOrder], list[SimEvent]]:
        """Entry + protective stop + target as one unit (the default path)."""
        symbol = symbol.upper()
        exit_side: Side = "sell" if side == "buy" else "buy"
        if side == "buy" and not (target_price > stop_price):
            raise OrderError("long bracket needs target above stop")
        if side == "sell" and not (target_price < stop_price):
            raise OrderError("short bracket needs target below stop")
        bracket = f"b{next(self._bracket_ids)}"
        entry = SimOrder(
            id=self._next_id(), symbol=symbol, side=side, type=entry_type, qty=qty,
            limit_price=limit_price if entry_type == "limit" else None,
            bracket_id=bracket, role="entry", placed_ts=ts, setup_id=setup_id,
        )
        events = self._validate_entry(entry, ts, opens_position=True)
        if events:
            return [entry], events
        stop = SimOrder(
            id=self._next_id(), symbol=symbol, side=exit_side, type="stop", qty=qty,
            stop_price=stop_price, bracket_id=bracket, role="stop",
            status="pending", placed_ts=ts,
        )
        target = SimOrder(
            id=self._next_id(), symbol=symbol, side=exit_side, type="limit", qty=qty,
            limit_price=target_price, bracket_id=bracket, role="target",
            status="pending", placed_ts=ts,
        )
        for o in (entry, stop, target):
            self.orders[o.id] = o
        return [entry, stop, target], []

    def _validate_entry(
        self, order: SimOrder, ts: datetime, opens_position: bool
    ) -> list[SimEvent]:
        if order.qty < 1:
            return self._reject(order, ts, "quantity must be at least 1 share")
        if order.type == "limit" and not order.limit_price:
            return self._reject(order, ts, "limit order needs a limit price")
        if order.type == "stop" and not order.stop_price:
            return self._reject(order, ts, "stop order needs a stop price")
        if self.flattened:
            return self._reject(order, ts, "session is past the close (EOD flatten)")
        if opens_position:
            if order.symbol in self.positions:
                return self._reject(
                    order, ts, f"already holding {order.symbol} — one position per symbol"
                )
            pending_entry = any(
                o.status == "working" and o.role in ("standalone", "entry") and o.symbol == order.symbol
                for o in self.orders.values()
            )
            if pending_entry:
                return self._reject(order, ts, f"an entry for {order.symbol} is already working")
            ref = self._entry_ref_price(order)
            if ref <= 0:
                return self._reject(order, ts, "no reference price yet — reveal a bar first")
            notional = order.qty * ref
            if notional > self.buying_power_left() + 1e-9:
                return self._reject(
                    order, ts,
                    f"buying power exceeded: ${notional:,.0f} needed, "
                    f"${max(self.buying_power_left(), 0):,.0f} available",
                )
        return []

    def cancel(self, order_id: int, ts: datetime) -> list[SimEvent]:
        order = self.orders.get(order_id)
        if order is None or order.status not in ("working", "pending"):
            raise OrderError("order is not open")
        return self._cancel_order(order, ts, "canceled by user")

    def _cancel_order(self, order: SimOrder, ts: datetime, reason: str) -> list[SimEvent]:
        order.status = "canceled"
        order.reason = reason
        events = [SimEvent("cancel", ts, order.symbol, order.id, reason)]
        if order.role == "entry" and order.bracket_id:
            for sibling in self._bracket_siblings(order):
                if sibling.status == "pending":
                    sibling.status = "canceled"
                    sibling.reason = "entry canceled"
        return events

    def _bracket_siblings(self, order: SimOrder) -> list[SimOrder]:
        if not order.bracket_id:
            return []
        return [
            o for o in self.orders.values()
            if o.bracket_id == order.bracket_id and o.id != order.id
        ]

    # ------------------------------------------------------------ bar pipeline

    def on_bar(self, bar: Bar) -> list[SimEvent]:
        """Process one newly revealed bar. Order of evaluation inside a bar:
        entries first (they fill at the open), then protective stops, then
        targets — so a same-bar stop+target conflict resolves to the stop."""
        events: list[SimEvent] = []
        self.last_close[bar.symbol] = bar.close

        for order in self._open_orders(bar.symbol, roles=("standalone", "entry")):
            events += self._try_fill_entry(order, bar)
        for order in self._open_orders(bar.symbol, roles=("stop",)):
            events += self._try_fill_stop(order, bar)
        for order in self._open_orders(bar.symbol, roles=("target",)):
            events += self._try_fill_target(order, bar)
        for order in self._open_orders(bar.symbol, roles=("exit",)):
            events += self._try_fill_manual_exit(order, bar)
        return events

    def _open_orders(self, symbol: str, roles: tuple[str, ...]) -> list[SimOrder]:
        return [
            o for o in sorted(self.orders.values(), key=lambda o: o.id)
            if o.symbol == symbol and o.status == "working" and o.role in roles
        ]

    def _try_fill_entry(self, order: SimOrder, bar: Bar) -> list[SimEvent]:
        if order.placed_ts is not None and bar.ts < order.placed_ts:
            return []
        price: float | None = None
        if order.type == "market":
            price = bar.open  # the NEXT bar's open — honest immediacy cost
        elif order.type == "limit":
            assert order.limit_price is not None
            if order.side == "buy":
                if bar.open <= order.limit_price:
                    price = bar.open  # gapped through: you get the better print
                elif bar.low <= order.limit_price:
                    price = order.limit_price
            else:
                if bar.open >= order.limit_price:
                    price = bar.open
                elif bar.high >= order.limit_price:
                    price = order.limit_price
        elif order.type == "stop":  # stop-entry (breakout order)
            assert order.stop_price is not None
            if order.side == "buy":
                if bar.open >= order.stop_price:
                    price = bar.open  # gapped past: worse price, honestly
                elif bar.high >= order.stop_price:
                    price = order.stop_price
            else:
                if bar.open <= order.stop_price:
                    price = bar.open
                elif bar.low <= order.stop_price:
                    price = order.stop_price
        if price is None:
            return []
        return self._fill_entry(order, bar, price)

    def _fill_entry(self, order: SimOrder, bar: Bar, price: float) -> list[SimEvent]:
        order.status = "filled"
        order.filled_ts = bar.ts
        order.fill_price = price
        signed = order.qty if order.side == "buy" else -order.qty
        self.cash -= signed * price
        initial_stop = None
        for sibling in self._bracket_siblings(order):
            if sibling.status == "pending":
                sibling.status = "working"  # exits go live with the position
            if sibling.role == "stop":
                initial_stop = sibling.stop_price
        self.positions[order.symbol] = Position(
            symbol=order.symbol, qty=signed, avg_price=price, entry_ts=bar.ts,
            initial_stop=initial_stop, entry_order_id=order.id, setup_id=order.setup_id,
        )
        self.trades.append(
            Trade(
                id=len(self.trades) + 1, symbol=order.symbol,
                direction="long" if signed > 0 else "short", qty=order.qty,
                entry_ts=bar.ts, entry_price=price, stop_price=initial_stop,
                setup_id=order.setup_id,
                grade=self.pending_grades.pop(order.symbol, None),
            )
        )
        detail = f"{order.side} {order.qty} {order.symbol} @ {price:.2f}"
        return [SimEvent("fill", bar.ts, order.symbol, order.id, detail)]

    def _try_fill_stop(self, order: SimOrder, bar: Bar) -> list[SimEvent]:
        assert order.stop_price is not None
        if order.side == "sell":  # protecting a long
            if bar.open <= order.stop_price:
                return self._exit(order, bar, bar.open, "stop")  # gapped past
            if bar.low <= order.stop_price:
                return self._exit(order, bar, order.stop_price, "stop")
        else:  # protecting a short
            if bar.open >= order.stop_price:
                return self._exit(order, bar, bar.open, "stop")
            if bar.high >= order.stop_price:
                return self._exit(order, bar, order.stop_price, "stop")
        return []

    def _try_fill_target(self, order: SimOrder, bar: Bar) -> list[SimEvent]:
        assert order.limit_price is not None
        if order.side == "sell":  # long target above
            if bar.open >= order.limit_price:
                return self._exit(order, bar, bar.open, "target")
            if bar.high >= order.limit_price:
                return self._exit(order, bar, order.limit_price, "target")
        else:  # short target below
            if bar.open <= order.limit_price:
                return self._exit(order, bar, bar.open, "target")
            if bar.low <= order.limit_price:
                return self._exit(order, bar, order.limit_price, "target")
        return []

    def _try_fill_manual_exit(self, order: SimOrder, bar: Bar) -> list[SimEvent]:
        """User-placed close: market at next open; limit/stop by their rules."""
        if order.placed_ts is not None and bar.ts < order.placed_ts:
            return []
        if order.type == "market":
            return self._exit(order, bar, bar.open, "manual")
        if order.type == "limit":
            assert order.limit_price is not None
            if order.side == "sell":
                if bar.open >= order.limit_price:
                    return self._exit(order, bar, bar.open, "manual")
                if bar.high >= order.limit_price:
                    return self._exit(order, bar, order.limit_price, "manual")
            else:
                if bar.open <= order.limit_price:
                    return self._exit(order, bar, bar.open, "manual")
                if bar.low <= order.limit_price:
                    return self._exit(order, bar, order.limit_price, "manual")
            return []
        return self._try_fill_stop(order, bar)  # manual stop: same mechanics

    def _exit(self, order: SimOrder, bar: Bar, price: float, reason: str) -> list[SimEvent]:
        position = self.positions.get(order.symbol)
        if position is None:  # defensive: exit without position can't happen
            return self._cancel_order(order, bar.ts, "no position to exit")
        order.status = "filled"
        order.filled_ts = bar.ts
        order.fill_price = price
        self.cash += position.qty * price
        del self.positions[order.symbol]
        # Position is gone: EVERY other open exit-side order on this symbol
        # dies with it (bracket legs AND manual exits — no orphans, ever).
        for other in self.orders.values():
            if (
                other.id != order.id
                and other.symbol == order.symbol
                and other.status in ("working", "pending")
                and other.role in ("stop", "target", "exit")
            ):
                other.status = "canceled"
                other.reason = f"OCO: {reason} filled"
        self._close_trade(order.symbol, bar.ts, price, reason)
        detail = f"{order.side} {order.qty} {order.symbol} @ {price:.2f} ({reason})"
        return [SimEvent("fill", bar.ts, order.symbol, order.id, detail)]

    def _close_trade(self, symbol: str, ts: datetime, price: float, reason: str) -> None:
        for trade in reversed(self.trades):
            if trade.symbol == symbol and not trade.closed:
                trade.exit_ts = ts
                trade.exit_price = price
                trade.exit_reason = reason
                if trade.stop_price is not None:
                    per_share_risk = abs(trade.entry_price - trade.stop_price)
                    if per_share_risk >= 0.01:
                        pnl = price - trade.entry_price
                        if trade.direction == "short":
                            pnl = -pnl
                        trade.r_multiple = round(pnl / per_share_risk, 3)
                return

    # ---------------------------------------------------------------- the bell

    def on_clock(self, clock: datetime, cal_day: CalendarDay) -> list[SimEvent]:
        """EOD discipline (doc §9): warning before the close, forced flatten
        at it — timed off the CALENDAR row, so half days behave (§16.1)."""
        events: list[SimEvent] = []
        close = cal_day.close_utc()
        warn_at = close - timedelta(minutes=EOD_WARN_MINUTES)
        if not self._eod_warned and clock >= warn_at and clock < close and self.positions:
            self._eod_warned = True
            events.append(
                SimEvent("eod_warning", clock, None, None,
                         f"market closes {EOD_WARN_MINUTES} min from now — flatten or be flattened")
            )
        if clock >= close and not self.flattened:
            self.flattened = True
            for symbol in list(self.positions):
                position = self.positions.pop(symbol)
                price = self.last_close.get(symbol, position.avg_price)
                self.cash += position.qty * price
                self._close_trade(symbol, clock, price, "eod")
                events.append(
                    SimEvent("eod_flatten", clock, symbol, None,
                             f"forced EOD close: {abs(position.qty)} {symbol} @ {price:.2f}")
                )
            for order in self.orders.values():
                if order.status in ("working", "pending"):
                    order.status = "canceled"
                    order.reason = "end of day"
        return events
