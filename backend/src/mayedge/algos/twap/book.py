from __future__ import annotations

from typing import Any

from mayedge.algos.clip_book import AlgoPayload, ClipBook
from mayedge.algos.twap.job import AdvancedTwapRunner
from mayedge.algos.twap.plan import (
    ALGO_ID,
    TWAP_COI_BASE,
    TWAP_COI_END,
    AdvancedTwapParams,
    validate_params,
)
from mayedge.numbers import parse_decimal

__all__ = ["AdvancedTwapBook", "AlgoPayload"]

ID_PREFIX = "TW-"


class AdvancedTwapBook(ClipBook[AdvancedTwapRunner]):
    """Many advanced-TWAP jobs. Native exchange TWAP does not live here."""

    ALGO_ID = ALGO_ID
    ID_PREFIX = ID_PREFIX
    LABEL = "TWAP"
    COI_BASE = TWAP_COI_BASE
    COI_END = TWAP_COI_END
    # A TWAP slice reads the book when it is due; resume does not wait for feeds.
    RESTORE_WAITS_FOR_FEEDS = False

    def _new_runner(self) -> AdvancedTwapRunner:
        return AdvancedTwapRunner(self)

    def _view(self, job: AdvancedTwapRunner) -> AdvancedTwapRunner:
        return job

    async def start_from_body(self, body: dict[str, Any]) -> None:
        side = body.get("side")
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        max_price = parse_decimal(str(body["max_price"])) if body.get("max_price") else None
        max_index = parse_decimal(str(body["max_index_pct"])) if body.get("max_index_pct") else None
        params = AdvancedTwapParams(
            side=side,
            qty=parse_decimal(str(body["qty"])),
            duration_seconds=int(body["duration_seconds"]),
            frequency_seconds=int(body.get("frequency_seconds", 5)),
            style=body.get("style") or "neutral",
            randomize=bool(body.get("randomize", True)),
            max_price=max_price,
            max_index_pct=max_index,
        )
        validate_params(params)
        await self.start(
            market_index=int(body["market_index"]),
            params=params,
            reduce_only=bool(body.get("reduce_only", False)),
        )

    async def start(
        self,
        *,
        market_index: int,
        params: AdvancedTwapParams,
        reduce_only: bool = False,
    ) -> None:
        await self._ensure_book(market_index)

        async def begin(job: AdvancedTwapRunner, algo_id: str) -> None:
            await job.start(
                algo_id=algo_id, market_index=market_index, params=params, reduce_only=reduce_only
            )

        await self._launch(begin)
