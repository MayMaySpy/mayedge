from __future__ import annotations

import logging
from typing import Any

from mayedge.algos import common
from mayedge.algos.chase.fills import may_invent_fill
from mayedge.algos.chase.iceberg import (
    ALGO_ID,
    ALGO_VERSION,
    ChaseIcebergParams,
)
from mayedge.algos.chase.state import (
    ACTIVE_STATUSES,
    ChaseState,
    ChaseStatus,
    ClipBookView,
    ClipState,
)
from mayedge.algos.clip_job import ClipJob
from mayedge.config import settings
from mayedge.numbers import check_notional, fmt_decimal, to_decimal

logger = logging.getLogger(__name__)

__all__ = [
    "ACTIVE_STATUSES",
    "ALGO_ID",
    "ALGO_VERSION",
    "ChaseIcebergRunner",
    "ChaseState",
    "ChaseStatus",
    "ClipBookView",
    "may_invent_fill",
]


class ChaseIcebergRunner(ClipJob[ClipBookView, ChaseState]):
    """One chase job. ChaseBook owns many of these."""

    def __init__(self, book: ClipBookView) -> None:
        super().__init__(book, ChaseState())

    def snapshot(self, s: ChaseState | None = None) -> dict[str, Any]:
        s = s or self._state
        self._reconcile_master()
        p = s.params
        live = s.ledger.working()
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": s.algo_id or None,
            "status": s.status.value,
            "market_index": s.market_index,
            "symbol": s.symbol,
            "reduce_only": s.reduce_only,
            "side": p.side if p else None,
            "qty": fmt_decimal(p.qty) if p else None,
            "display_qty": fmt_decimal(p.display_qty) if p else None,
            "offset_bps": fmt_decimal(p.offset_bps) if p else None,
            "price_floor": fmt_decimal(p.price_floor) if p else None,
            "price_ceiling": fmt_decimal(p.price_ceiling) if p else None,
            "remaining": fmt_decimal(s.remaining),
            "filled": fmt_decimal(s.filled),
            "quote_action": s.quote_action,
            "reason": s.reason,
            "rest_price": fmt_decimal(s.rest_price),
            "rest_qty": fmt_decimal(s.rest_qty),
            "working_coi": live.client_order_index if live else None,
            "working_order_index": str(live.order_index) if live and live.order_index else None,
            "error": s.error,
            "created_at": s.created_at or None,
            **s.ledger.to_dict(),
        }

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        """Rebuild in-memory state from a DB row (does not start the loop)."""
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise ValueError(f"unrecoverable chase row {row.get('algo_id')}: bad side")
        for key in ("qty", "display_qty", "offset_bps", "price_floor", "price_ceiling"):
            if row.get(key) is None:
                raise ValueError(f"unrecoverable chase row {row.get('algo_id')}: missing {key}")
        params = ChaseIcebergParams(
            side=side,
            qty=to_decimal(row["qty"]),
            display_qty=to_decimal(row["display_qty"]),
            offset_bps=to_decimal(row["offset_bps"]),
            price_floor=to_decimal(row["price_floor"]),
            price_ceiling=to_decimal(row["price_ceiling"]),
        )
        self._restore_state(ChaseState(params=params, **ClipState.fields_from_row(row)))
        self._reconcile_master()

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        params: ChaseIcebergParams,
        reduce_only: bool = False,
    ) -> None:
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        if params.qty <= 0 or params.display_qty <= 0:
            raise ValueError("Size and display qty must be > 0")
        if params.price_floor >= params.price_ceiling:
            raise ValueError("Floor must be below ceiling")
        if params.offset_bps < 0:
            raise ValueError("offset_bps must be ≥ 0")

        ref_price = self._parent_ref_price(params, market_index)
        check_notional(params.qty, ref_price, settings.max_order_notional)

        self._state = ChaseState(
            status=ChaseStatus.RUNNING,
            params=params,
            market_index=market_index,
            symbol=meta.symbol,
            reduce_only=reduce_only,
            remaining=params.qty,
            algo_id=algo_id,
            created_at=common.now_ms(),
        )
        self._cois.clear()
        self._reset_job()
        await self._begin()
