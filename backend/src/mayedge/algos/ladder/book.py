from __future__ import annotations

from decimal import Decimal
from typing import Any

from mayedge.algos.clip_book import AlgoPayload, ClipBook
from mayedge.algos.ladder.config import DEFAULT_WINDOW, LADDER_COI_BASE, LADDER_COI_END
from mayedge.algos.ladder.job import LadderRunner
from mayedge.algos.ladder.plan import ALGO_ID, LadderParams, NumericLcg, validate_params
from mayedge.algos.ladder.state import LadderState
from mayedge.lighter.models import maker_min_base
from mayedge.numbers import parse_decimal

__all__ = ["AlgoPayload", "LadderBook"]

ID_PREFIX = "LD-"


class LadderBook(ClipBook[LadderRunner]):
    """Many ladder jobs, one per Market and side. Start does not replace a live one."""

    ALGO_ID = ALGO_ID
    ID_PREFIX = ID_PREFIX
    LABEL = "Ladder"
    COI_BASE = LADDER_COI_BASE
    COI_END = LADDER_COI_END

    def _new_runner(self) -> LadderRunner:
        return LadderRunner(self)

    def _view(self, job: LadderRunner) -> LadderState:
        return job.state

    def _side(self, job: LadderRunner) -> str | None:
        params = job.state.params
        return params.side if params else None

    def _market_limits(self, market_index: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """Tick, lot, base minimum, and quote minimum. The quote minimum is checked
        at each rung's own price, not at the touch (a rung at 0.005 needs 4× the size
        of one at 0.02)."""
        ex = self.execution()
        meta = ex.get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        tick = Decimal(10) ** -meta.price_decimals
        qty_step = Decimal(10) ** -meta.size_decimals
        min_qty = maker_min_base(meta.min_base_amount, 0, None, qty_step)
        if min_qty <= 0:
            min_qty = qty_step
        min_quote = Decimal(str(meta.min_quote_amount or 0))
        return tick, qty_step, min_qty, min_quote

    async def start_from_body(self, body: dict[str, Any]) -> None:
        side = body.get("side")
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        market_index = int(body["market_index"])
        rungs = int(body.get("rungs") or body.get("orders") or 20)
        params = LadderParams(
            side=side,
            qty=parse_decimal(str(body["qty"])),
            price_from=parse_decimal(str(body["price_from"])),
            price_to=parse_decimal(str(body["price_to"])),
            rungs=rungs,
            window=int(body.get("window", DEFAULT_WINDOW)),
            size_var_pct=parse_decimal(str(body.get("size_var_pct") or "0")),
            price_var_pct=parse_decimal(str(body.get("price_var_pct") or "0")),
            size_skew=parse_decimal(str(body.get("size_skew") or "0")),
        )
        tick, qty_step, min_qty, min_quote = self._market_limits(market_index)
        seed_raw = body.get("seed")
        rng = None
        if (
            (params.size_var_pct > 0 or params.price_var_pct > 0)
            and seed_raw is not None
            and str(seed_raw) != ""
        ):
            rng = NumericLcg(int(seed_raw))
        validate_params(
            params, tick=tick, qty_step=qty_step, min_qty=min_qty, rng=rng, min_quote=min_quote
        )
        await self.start(
            market_index=market_index,
            params=params,
            reduce_only=bool(body.get("reduce_only", False)),
        )

    async def start(
        self,
        *,
        market_index: int,
        params: LadderParams,
        reduce_only: bool = False,
    ) -> None:
        await self._ensure_book(market_index)
        if self.live_on_market_side(market_index, params.side):
            raise ValueError(f"Ladder already running on market {market_index} side {params.side}")

        async def begin(job: LadderRunner, algo_id: str) -> None:
            await job.start(
                algo_id=algo_id, market_index=market_index, params=params, reduce_only=reduce_only
            )

        await self._launch(begin)
