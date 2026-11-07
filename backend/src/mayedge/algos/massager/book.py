"""The Massager's book. Desk wiring (exclusivity, the desk registry) is phase 3."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.clip_book import AlgoPayload, ClipBook
from mayedge.algos.massager.config import MASSAGER_COI_BASE, MASSAGER_COI_END
from mayedge.algos.massager.job import MassagerRunner
from mayedge.algos.massager.plan import ALGO_ID, MassagerParams
from mayedge.algos.massager.state import MassagerState
from mayedge.numbers import parse_decimal

MarketConflictFn = Callable[[int], bool]


class MassagerBook(ClipBook[MassagerRunner]):
    """One Massager per Market (massager-scope.md §3)."""

    ALGO_ID = ALGO_ID
    ID_PREFIX = "MS-"
    LABEL = "Massager"
    COI_BASE = MASSAGER_COI_BASE
    COI_END = MASSAGER_COI_END

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int | None = None,
        coi_end: int | None = None,
        missing_fill_grace_ms: int = 800,
        market_conflict: MarketConflictFn | None = None,
    ) -> None:
        super().__init__(
            execution=execution,
            broadcast=broadcast,
            coi_base=coi_base,
            coi_end=coi_end,
            missing_fill_grace_ms=missing_fill_grace_ms,
        )
        self._market_conflict = market_conflict

    def set_market_conflict(self, fn: MarketConflictFn) -> None:
        self._market_conflict = fn

    def _new_runner(self) -> MassagerRunner:
        return MassagerRunner(self)

    def _view(self, job: MassagerRunner) -> MassagerState:
        return job.state

    async def start_from_body(self, body: dict[str, Any]) -> None:
        params = MassagerParams(
            band_low=parse_decimal(str(body["band_low"])),
            band_high=parse_decimal(str(body["band_high"])),
            swing=parse_decimal(str(body["swing"])),
            clip=parse_decimal(str(body["clip"])),
        )
        await self.start(market_index=int(body["market_index"]), params=params)

    async def start(self, *, market_index: int, params: MassagerParams) -> None:
        await self._ensure_book(market_index)
        if self.live_on_market(market_index):
            raise ValueError("A Massager is already running on this Market")
        if self._market_conflict and self._market_conflict(market_index):
            raise ValueError("A Planner, Trail or Grid runs this Market's orders")

        async def begin(job: MassagerRunner, algo_id: str) -> None:
            await job.start(algo_id=algo_id, market_index=market_index, params=params)

        await self._launch(begin)
