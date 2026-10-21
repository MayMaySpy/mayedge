from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.clip_book import AlgoPayload, ClipBook
from mayedge.algos.grid.config import GRID_COI_BASE, GRID_COI_END
from mayedge.algos.grid.decide import ALGO_ID, GridParams
from mayedge.algos.grid.job import GridRunner
from mayedge.algos.grid.state import GridState
from mayedge.numbers import parse_decimal

__all__ = ["AlgoPayload", "ChaseGridBook", "MarketConflictFn"]

ID_PREFIX = "CG-"

MarketConflictFn = Callable[[int], bool]


class ChaseGridBook(ClipBook[GridRunner]):
    """One chase-grid job per market, alone among desk algos there (ADR 0002)."""

    ALGO_ID = ALGO_ID
    ID_PREFIX = ID_PREFIX
    LABEL = "Chase-grid"
    COI_BASE = GRID_COI_BASE
    COI_END = GRID_COI_END

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

    def _new_runner(self) -> GridRunner:
        return GridRunner(self)

    def _view(self, job: GridRunner) -> GridState:
        return job.state

    async def start_from_body(self, body: dict[str, Any]) -> None:
        profit = body.get("profit_bps")
        if profit is None:
            raise ValueError("profit_bps is required")
        grid_bps = body.get("grid_bps", profit)
        params = GridParams(
            max_inventory=parse_decimal(str(body["qty"])),
            display_qty=parse_decimal(str(body["display_qty"])),
            offset_bps=parse_decimal(str(body.get("offset_bps", "4"))),
            profit_bps=parse_decimal(str(profit)),
            grid_bps=parse_decimal(str(grid_bps)),
            price_floor=parse_decimal(str(body["price_floor"])),
            price_ceiling=parse_decimal(str(body["price_ceiling"])),
            be_delay_ms=int(body.get("be_delay_ms") or 0),
        )
        await self.start(market_index=int(body["market_index"]), params=params)

    async def start(self, *, market_index: int, params: GridParams) -> None:
        await self._ensure_book(market_index)
        if self.live_on_market(market_index):
            raise ValueError(f"Chase-grid already running on market {market_index}")
        if self._market_conflict and self._market_conflict(market_index):
            raise ValueError(f"Another desk algo is already running on market {market_index}")

        async def begin(job: GridRunner, algo_id: str) -> None:
            await job.start(algo_id=algo_id, market_index=market_index, params=params)

        await self._launch(begin)
