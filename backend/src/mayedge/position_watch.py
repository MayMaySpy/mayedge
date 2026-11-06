"""The Position watch: pushes about the operator's own Positions. No venue call, no order.

Rules: docs/position-rules.md, ADR 0024. The checks are pure (`PositionWatch.look`); the loop
below gathers what the desk already holds and hands the pushes to `emit`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mayedge.push_text import _at_minutes, _minutes, _px, _signed_usd, _trim, _usd, _utc_date

logger = logging.getLogger(__name__)

CHECK_S = 10.0
# E2, E3. Halfway to the stop, then one and two R in profit.
R_LEVELS = (-0.5, 1.0, 2.0)
# E4 reads the last closed bar of this size.
CLOSE_S = 3_600
# E7 names a liquidation price this close.
LIQ_NEAR_PCT = 25.0
GUARD_ALGOS = frozenset({"planner", "trail"})
GUARD_STATUS = frozenset({"running", "paused"})


@dataclass(frozen=True)
class WatchSettings:
    no_stop_after_s: float = 300.0
    bleed_r: float = 0.25
    brief_at: str = "07:00"


@dataclass(frozen=True)
class Held:
    """One open Position as the watch sees it. Size is unsigned; side says which way."""

    market_index: int
    symbol: str
    side: str
    size: float
    entry: float
    mark: float
    liq: float = 0.0
    trip: str = ""
    funding: float | None = None

    @property
    def sign(self) -> float:
        return 1.0 if self.side == "long" else -1.0

    @property
    def upnl(self) -> float:
        return (self.mark - self.entry) * self.size * self.sign


@dataclass(frozen=True)
class StopOrder:
    market_index: int
    side: str
    trigger: float


@dataclass(frozen=True)
class IdeaStop:
    symbol: str
    side: str
    stop: float
    updated_at: int = 0


@dataclass
class Look:
    """Everything one tick reads (PW1)."""

    positions: list[Held] = field(default_factory=list)
    stops: list[StopOrder] = field(default_factory=list)
    guarded: set[int] = field(default_factory=set)
    ideas: list[IdeaStop] = field(default_factory=list)
    # Market index → (funding %/h, sigmas from its day), for markets on the funding strip.
    crowded: dict[int, tuple[float, float]] = field(default_factory=dict)
    # Market index → close of the last closed 1h bar.
    closes: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Push:
    key: str
    text: str
    urgent: bool = False


@dataclass
class _Trip:
    first_stop: float | None = None
    seen: set[str] = field(default_factory=set)
    crowded_on: str = ""


def trip_id(pos: Held) -> str:
    """PW2. The journal's Round trip, else the Market and side."""
    return pos.trip or f"{pos.market_index}:{pos.side}"


def stop_price(pos: Held, stops: list[StopOrder]) -> float | None:
    """S1, S2. The trigger of the protecting Stop nearest to mark."""
    closing = "sell" if pos.side == "long" else "buy"
    triggers = [
        s.trigger
        for s in stops
        if s.market_index == pos.market_index and s.side == closing and s.trigger > 0
    ]
    if not triggers:
        return None
    return min(triggers, key=lambda px: abs(pos.mark - px))


def idea_stop(pos: Held, ideas: list[IdeaStop]) -> float | None:
    """S3. The newest open Idea on this Market and side that has a stop."""
    mine = [i for i in ideas if i.symbol == pos.symbol and i.side == pos.side and i.stop > 0]
    if not mine:
        return None
    return max(mine, key=lambda i: i.updated_at).stop


def r_multiple(pos: Held, plan_stop: float | None) -> float | None:
    """S4. The move in the Position's favour over the distance from entry to the plan stop."""
    if plan_stop is None or pos.entry <= 0 or pos.mark <= 0:
        return None
    risk = abs(pos.entry - plan_stop)
    if risk <= 0:
        return None
    return (pos.mark - pos.entry) * pos.sign / risk


def _r(value: float) -> str:
    sign = "−" if value < 0 else "+"
    return f"{sign}{abs(value):.1f}R"


def _size(value: float) -> str:
    text = f"{value:,.4f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _name(pos: Held) -> str:
    return f"{pos.symbol} {pos.side}"


class PositionWatch:
    def __init__(self, cfg: WatchSettings | None = None) -> None:
        self._cfg = cfg or WatchSettings()
        self._trips: dict[str, _Trip] = {}
        self._unprotected_since: dict[int, float] = {}
        self._told: frozenset[int] = frozenset()
        self._brief_on: str | None = None
        self._looked = False

    def look(self, look: Look, now: float) -> list[Push]:
        out: list[Push] = []
        live: set[str] = set()
        plan: dict[str, float | None] = {}
        # PW3: the first look after the desk starts only seeds what is already true.
        first = not self._looked
        self._looked = True
        for pos in look.positions:
            tid = trip_id(pos)
            live.add(tid)
            trip = self._trips.setdefault(tid, _Trip())
            stop = stop_price(pos, look.stops)
            if trip.first_stop is None and stop is not None:
                trip.first_stop = stop
            ps = idea_stop(pos, look.ideas)
            plan[tid] = ps if ps is not None else trip.first_stop
            out.extend(self._levels(pos, tid, trip, plan[tid], first))
            out.extend(self._thesis(pos, tid, trip, look, first))
            out.extend(self._crowded(pos, tid, trip, look, now, first))
            out.extend(self._bleed(pos, tid, trip, plan[tid], first))
        # PW2: a Position gone flat forgets its Round trip.
        for tid in list(self._trips):
            if tid not in live:
                del self._trips[tid]
        out.extend(self._no_stop(look, now))
        out.extend(self._brief(look, plan, now))
        return out

    def _levels(
        self, pos: Held, tid: str, trip: _Trip, plan_stop: float | None, first: bool
    ) -> list[Push]:
        """E2, E3. Levels crossed in one look send only the furthest."""
        r = r_multiple(pos, plan_stop)
        if r is None or plan_stop is None:
            return []
        crossed: list[float] = []
        for level in R_LEVELS:
            name = f"r{level:g}"
            hit = r <= level if level < 0 else r >= level
            if hit and name not in trip.seen:
                trip.seen.add(name)
                crossed.append(level)
        if first or not crossed:
            return []
        out: list[Push] = []
        losses = [lv for lv in crossed if lv < 0]
        gains = [lv for lv in crossed if lv > 0]
        for level in ([min(losses)] if losses else []) + ([max(gains)] if gains else []):
            name = f"r{level:g}"
            if level < 0:
                text = (
                    f"{_name(pos)}: halfway to the stop, {_r(r)} "
                    f"(mark {_px(pos.mark)}, stop {_px(plan_stop)})"
                )
            else:
                text = f"{_name(pos)}: {_r(r)} (mark {_px(pos.mark)}, entry {_px(pos.entry)})"
            out.append(Push(f"position:{tid}:{name}", text))
        return out

    def _thesis(self, pos: Held, tid: str, trip: _Trip, look: Look, first: bool) -> list[Push]:
        """E4. The last closed 1h bar beyond the Idea's stop. Once per Round trip."""
        stop = idea_stop(pos, look.ideas)
        close = look.closes.get(pos.market_index)
        if stop is None or close is None or close <= 0 or "thesis" in trip.seen:
            return []
        through = close < stop if pos.side == "long" else close > stop
        if not through:
            return []
        trip.seen.add("thesis")
        if first:
            return []
        word = "under" if pos.side == "long" else "over"
        text = f"🔴 {_name(pos)}: the 1h bar closed at {_px(close)}, {word} the Idea's stop {_px(stop)}"
        return [Push(f"position:{tid}:thesis", text, urgent=True)]

    def _crowded(
        self, pos: Held, tid: str, trip: _Trip, look: Look, now: float, first: bool
    ) -> list[Push]:
        """E5. On the funding strip with this side paying. Once per Round trip per UTC day."""
        row = look.crowded.get(pos.market_index)
        if row is None:
            return []
        funding, z = row
        pays = funding > 0 if pos.side == "long" else funding < 0
        day = _utc_date(time.gmtime(now))
        if not pays or trip.crowded_on == day:
            return []
        trip.crowded_on = day
        if first:
            return []
        payer = "longs" if pos.side == "long" else "shorts"
        text = (
            f"{_name(pos)}: crowded, funding {funding:+.4f}%/h is {abs(z):.1f}σ "
            f"from its day, and {payer} pay"
        )
        return [Push(f"position:{tid}:crowded:{day}", text)]

    def _bleed(
        self, pos: Held, tid: str, trip: _Trip, plan_stop: float | None, first: bool
    ) -> list[Push]:
        """E6. Funding has cost `bleed_r` of the Round trip's R in dollars."""
        if pos.funding is None or plan_stop is None or "bleed" in trip.seen:
            return []
        risk_usd = abs(pos.entry - plan_stop) * pos.size
        cost = -pos.funding
        if risk_usd <= 0 or cost < self._cfg.bleed_r * risk_usd:
            return []
        trip.seen.add("bleed")
        if first:
            return []
        text = (
            f"{_name(pos)}: funding has cost {_usd(cost)}, "
            f"{_trim(round(cost / risk_usd, 1))}R of its {_usd(risk_usd)} risk"
        )
        return [Push(f"position:{tid}:bleed", text)]

    def _no_stop(self, look: Look, now: float) -> list[Push]:
        """E1. One push for every unprotected Position, again only when a Market joins."""
        bare: dict[int, Held] = {}
        for pos in look.positions:
            guarded = pos.market_index in look.guarded
            if guarded or stop_price(pos, look.stops) is not None:
                continue
            bare[pos.market_index] = pos
        for mi in list(self._unprotected_since):
            if mi not in bare:
                del self._unprotected_since[mi]
        for mi in bare:
            self._unprotected_since.setdefault(mi, now)
        due = frozenset(
            mi
            for mi, since in self._unprotected_since.items()
            if now - since >= self._cfg.no_stop_after_s
        )
        # A protected Market leaves the told set, so it can join again.
        told = self._told & due
        joined = due - told
        self._told = due
        if not joined:
            return []
        rows = sorted((bare[mi] for mi in due), key=lambda p: -abs(p.size * p.mark))
        names = ", ".join(f"{_name(p)} {_size(p.size)}" for p in rows)
        count = len(rows)
        noun = "Position" if count == 1 else "Positions"
        markets = "-".join(str(mi) for mi in sorted(due))
        return [Push(f"position:nostop:{markets}", f"⚠️ No stop on {count} {noun}: {names}")]

    def _brief(self, look: Look, plan: dict[str, float | None], now: float) -> list[Push]:
        """E7. Once per UTC date at or past `brief_at`."""
        at = self._cfg.brief_at
        if not at or not look.positions:
            return []
        stamp = time.gmtime(now)
        day = _utc_date(stamp)
        if self._brief_on == day or _minutes(stamp) < _at_minutes(at):
            return []
        self._brief_on = day
        lines = [f"Positions, {at} UTC"]
        for pos in sorted(look.positions, key=lambda p: -abs(p.size * p.mark)):
            parts = [f"{_name(pos)} {_size(pos.size)}", _signed_usd(pos.upnl)]
            r = r_multiple(pos, plan.get(trip_id(pos)))
            if r is not None:
                parts.append(_r(r))
            stop = stop_price(pos, look.stops)
            if stop is not None and pos.mark > 0:
                parts.append(f"stop {abs(pos.mark - stop) / pos.mark * 100:.1f}% away")
            elif pos.market_index in look.guarded:
                parts.append("algo stop")
            else:
                parts.append("no stop")
            if pos.liq > 0 and pos.mark > 0:
                away = abs(pos.mark - pos.liq) / pos.mark * 100
                if away <= LIQ_NEAR_PCT:
                    parts.append(f"liq {away:.0f}% away")
            if pos.funding is not None:
                parts.append(f"funding {_signed_usd(pos.funding)}")
            lines.append(" · ".join(parts))
        return [Push(f"position:brief:{day}", "\n".join(lines))]


Gather = Callable[[], Awaitable[Look]]
Emit = Callable[[dict[str, Any]], None]


class PositionWatchLoop:
    def __init__(self, gather: Gather, emit: Emit, watch: PositionWatch) -> None:
        self._gather = gather
        self._emit = emit
        self._watch = watch
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def tick(self) -> int:
        look = await self._gather()
        pushes = self._watch.look(look, time.time())
        for p in pushes:
            self._emit({"type": "position_watch", "key": p.key, "text": p.text, "urgent": p.urgent})
        return len(pushes)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("position watch failed")
            await asyncio.sleep(CHECK_S)
