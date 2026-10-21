"""One Lighter Standard budget: 60 requests / rolling minute, sendTx included.

Class ceilings leave room for manual orders when algos and chart reads are busy.
A venue 429/405 cools every caller for 60s. Local refusal does not.
Kill is never refused here: it is sent whatever the window or cooldown says.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from typing import Any

from mayedge.lighter.errors import RATE_MSG, VenueBlocked

logger = logging.getLogger(__name__)

WINDOW_S = 60.0
CAP = 54
TX_CAP = 38
COOLDOWN_S = 60.0
KILL_LANE = "kill"
CEILING = {
    KILL_LANE: CAP,
    "critical": CAP,
    "algo": 44,
    "read": 40,
    "background": 25,
}
# sendTx ceilings. Algos stop short of TX_CAP so a manual order still fits.
TX_CEILING = {
    "algo": 30,
}
PUBLISH_S = 2.0

_lane: ContextVar[str] = ContextVar("lighter_budget_lane", default="critical")


class BudgetRefused(VenueBlocked):
    """Local limiter. Not a venue 429, so it must not start the firewall cooldown."""


class RestBudget:
    def __init__(self) -> None:
        self._hits: list[tuple[float, bool]] = []
        self._refusals: list[float] = []
        self._cool_until = 0.0
        self._cool_until_wall_ms = 0

    def reset(self) -> None:
        self._hits.clear()
        self._refusals.clear()
        self._cool_until = 0.0
        self._cool_until_wall_ms = 0

    def cooling(self) -> bool:
        return time.monotonic() < self._cool_until

    def note_blocked(self) -> None:
        self._cool_until = time.monotonic() + COOLDOWN_S
        self._cool_until_wall_ms = int((time.time() + COOLDOWN_S) * 1000)
        logger.warning("lighter rate limit — cooling %.0fs", COOLDOWN_S)

    def enter_lane(self, name: str) -> Token[str]:
        return _lane.set(name)

    def leave_lane(self, token: Token[str]) -> None:
        _lane.reset(token)

    def _prune(self, now: float) -> None:
        self._hits = [hit for hit in self._hits if now - hit[0] < WINDOW_S]
        self._refusals = [at for at in self._refusals if now - at < WINDOW_S]

    def _note_refused(self, now: float) -> None:
        self._prune(now)
        self._refusals.append(now)

    def snapshot(self) -> dict[str, Any]:
        """Requests and transactions in the last minute, against the desk's caps."""
        now = time.monotonic()
        self._prune(now)
        cooling = self._cool_until_wall_ms if now < self._cool_until else 0
        return {
            "type": "budget",
            "requests": len(self._hits),
            "requests_cap": CAP,
            "tx": sum(1 for _at, is_tx in self._hits if is_tx),
            "tx_cap": TX_CAP,
            "algo_tx_cap": TX_CEILING["algo"],
            "cooling_until": cooling,
            "refused_60s": len(self._refusals),
        }

    def _retry_after(self, now: float) -> int:
        if now < self._cool_until:
            return max(1, int(self._cool_until - now))
        if not self._hits:
            return 1
        return max(1, int(WINDOW_S - (now - self._hits[0][0])))

    def _fits(self, lane: str, n: int, *, tx: bool, now: float) -> bool:
        if lane == KILL_LANE:
            self._prune(now)
            return True
        if now < self._cool_until:
            return False
        self._prune(now)
        if len(self._hits) + n > CEILING[lane]:
            return False
        if tx:
            sent = sum(1 for _at, is_tx in self._hits if is_tx)
            if sent + n > TX_CEILING.get(lane, TX_CAP):
                return False
        return True

    def _grant(self, lane: str, n: int, *, tx: bool) -> bool:
        now = time.monotonic()
        if n <= 0:
            return self._fits(lane, 0, tx=False, now=now)
        if not self._fits(lane, n, tx=tx, now=now):
            return False
        self._hits.extend((now, tx) for _ in range(n))
        return True

    def tx_room(self, lane: str | None = None) -> int:
        """How many sendTx this lane could still spend now."""
        name = lane or _lane.get()
        now = time.monotonic()
        self._prune(now)
        sent = sum(1 for _at, is_tx in self._hits if is_tx)
        if name == KILL_LANE:
            return max(0, TX_CAP - sent)
        if now < self._cool_until:
            return 0
        return max(0, min(CEILING[name] - len(self._hits), TX_CEILING.get(name, TX_CAP) - sent))

    def try_acquire(self, n: int = 1, *, tx: bool = False, lane: str | None = None) -> bool:
        return self._grant(lane or _lane.get(), n, tx=tx)

    async def take(
        self,
        lane: str | None = None,
        n: int = 1,
        *,
        tx: bool = False,
        wait: bool = False,
    ) -> None:
        """Spend budget. ``wait`` sleeps until a slot frees (background backfill)."""
        name = lane or _lane.get()
        while True:
            if self._grant(name, n, tx=tx):
                return
            if not wait:
                now = time.monotonic()
                self._note_refused(now)
                raise BudgetRefused(429, f"{RATE_MSG} ({self._retry_after(now)}s)")
            await asyncio.sleep(0.25)


budget = RestBudget()


async def publish_changes(
    publish: Callable[[dict[str, Any]], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Publish the budget at most every two seconds, and only when it changed."""
    last: dict[str, Any] | None = None
    while True:
        await sleep(PUBLISH_S)
        snap = budget.snapshot()
        if snap == last:
            continue
        last = dict(snap)
        try:
            publish(snap)
        except Exception:
            logger.exception("budget publish failed")


def start_budget_publish(publish: Callable[[dict[str, Any]], None]) -> asyncio.Task[None]:
    return asyncio.create_task(publish_changes(publish), name="budget")
