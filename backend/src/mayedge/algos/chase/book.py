from __future__ import annotations

from typing import Any

from mayedge.algos.chase.config import CHASE_COI_BASE, CHASE_COI_END
from mayedge.algos.chase.iceberg import ALGO_ID, ChaseIcebergParams
from mayedge.algos.chase.job import ChaseIcebergRunner
from mayedge.algos.chase.state import ChaseState
from mayedge.algos.clip_book import AlgoPayload, ClipBook
from mayedge.numbers import parse_decimal

__all__ = ["AlgoPayload", "ChaseBook"]

ID_PREFIX = "CH-"


class ChaseBook(ClipBook[ChaseIcebergRunner]):
    """Many chase jobs, one per Market and side. Start does not replace a live one."""

    ALGO_ID = ALGO_ID
    ID_PREFIX = ID_PREFIX
    LABEL = "Chase"
    COI_BASE = CHASE_COI_BASE
    COI_END = CHASE_COI_END

    def _new_runner(self) -> ChaseIcebergRunner:
        return ChaseIcebergRunner(self)

    def _view(self, job: ChaseIcebergRunner) -> ChaseState:
        return job.state

    def _side(self, job: ChaseIcebergRunner) -> str | None:
        params = job.state.params
        return params.side if params else None

    async def start_from_body(self, body: dict[str, Any]) -> None:
        side = body.get("side")
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        params = ChaseIcebergParams(
            side=side,
            qty=parse_decimal(str(body["qty"])),
            display_qty=parse_decimal(str(body["display_qty"])),
            offset_bps=parse_decimal(str(body.get("offset_bps", "4"))),
            price_floor=parse_decimal(str(body["price_floor"])),
            price_ceiling=parse_decimal(str(body["price_ceiling"])),
        )
        await self.start(
            market_index=int(body["market_index"]),
            params=params,
            reduce_only=bool(body.get("reduce_only", False)),
        )

    async def start(
        self,
        *,
        market_index: int,
        params: ChaseIcebergParams,
        reduce_only: bool = False,
    ) -> None:
        await self._ensure_book(market_index)
        if self.live_on_market_side(market_index, params.side):
            raise ValueError(
                f"Chase already running on market {market_index} side {params.side}"
            )

        async def begin(job: ChaseIcebergRunner, algo_id: str) -> None:
            await job.start(
                algo_id=algo_id, market_index=market_index, params=params, reduce_only=reduce_only
            )

        await self._launch(begin)
