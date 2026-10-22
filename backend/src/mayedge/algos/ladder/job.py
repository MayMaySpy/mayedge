from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from mayedge.algos import common
from mayedge.algos.chase.iceberg import Action, leftover_is_dust
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.clip_job import ClipJob
from mayedge.algos.common import venue_order_keys
from mayedge.algos.ladder.config import MIN_PLACE_GAP_MS, is_ladder_client_order
from mayedge.algos.ladder.plan import (
    ALGO_ID,
    ALGO_VERSION,
    LadderParams,
    Rung,
    select_rungs_to_place,
    sort_by_closeness,
)
from mayedge.algos.ladder.state import LadderBookView, LadderState
from mayedge.algos.ledger import Ledger
from mayedge.config import settings
from mayedge.lighter.errors import (
    is_min_size,
    is_would_cross,
)
from mayedge.numbers import check_notional, fmt_decimal, to_decimal
from mayedge.rows import obj

logger = logging.getLogger(__name__)


class LadderRunner(ClipJob[LadderBookView, LadderState]):
    """One ladder job — keep-N live rungs on static prices."""

    LABEL = "ladder"

    def __init__(self, book: LadderBookView) -> None:
        super().__init__(book, LadderState())
        # Why the venue last refused a rung, for the blotter: "below_min_qty", "would_cross".
        self._place_refused: str | None = None

    def _orders_cancel_keys(self, orders: Any) -> set[tuple[int, int]]:
        return set(
            venue_order_keys(
                orders,
                lambda coi: is_ladder_client_order(coi) and coi in self._cois,
            )
        )

    async def _sync_fills(self) -> None:
        self._drain_trades()
        live = list(self._state.ledger.live_clips())
        if not live:
            self._reconcile_master()
            return
        for clip in live:
            await self._sync_clip(clip)
        self._reconcile_master()

    def snapshot(self, s: LadderState | None = None) -> dict[str, Any]:
        st = s if s is not None else self._state
        self._reconcile_master()
        p = st.params
        live = st.ledger.live_clips()
        per_rung = p.rung_list[0].qty if p and p.rung_list else None
        lo = hi = None
        if p:
            lo = min(p.price_from, p.price_to)
            hi = max(p.price_from, p.price_to)
        return {
            "type": "algo",
            "id": ALGO_ID,
            "algo_type": ALGO_ID,
            "version": ALGO_VERSION,
            "algo_id": st.algo_id or None,
            "status": st.status.value,
            "market_index": st.market_index,
            "symbol": st.symbol,
            "reduce_only": st.reduce_only,
            "side": p.side if p else None,
            "qty": fmt_decimal(p.qty) if p else None,
            "display_qty": fmt_decimal(per_rung) if per_rung is not None else None,
            "offset_bps": None,
            "price_floor": fmt_decimal(lo) if lo is not None else None,
            "price_ceiling": fmt_decimal(hi) if hi is not None else None,
            "remaining": fmt_decimal(st.remaining),
            "filled": fmt_decimal(st.filled),
            "quote_action": st.quote_action,
            "reason": st.reason,
            "rest_price": fmt_decimal(st.rest_price),
            "rest_qty": fmt_decimal(st.rest_qty),
            "working_coi": live[-1].client_order_index if live else None,
            "working_order_index": (
                str(live[-1].order_index) if live and live[-1].order_index else None
            ),
            "error": st.error,
            "created_at": st.created_at or None,
            "params_json": p.to_json() if p else {},
            **st.ledger.to_dict(),
        }

    def _sync_rest_from_live(self) -> None:
        params = self._state.params
        live = self._state.ledger.live_clips()
        if not live or not params:
            self._state.rest_price = None
            self._state.rest_qty = None
            return
        by_price = {r.price: r for r in params.rung_list}
        live_rungs = [by_price[c.price] for c in live if c.price in by_price]
        if live_rungs:
            closest = sort_by_closeness(live_rungs, params.side)[0]
            self._state.rest_price = closest.price
        total_rem = sum((c.remaining for c in live), Decimal("0"))
        self._state.rest_qty = total_rem if total_rem > 0 else Decimal(len(live))

    def hydrate_from_row(self, row: dict[str, Any]) -> None:
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise ValueError(f"unrecoverable ladder row {row.get('algo_id')}: bad side")
        raw = obj(row.get("params_json"))
        if not raw.get("rung_list"):
            raise ValueError(f"unrecoverable ladder row {row.get('algo_id')}: missing rung_list")
        params = LadderParams.from_json(
            raw,
            side=side,
            qty=to_decimal(row.get("qty") or raw.get("qty") or "0"),
            price_from=to_decimal(raw.get("price_from") or row.get("price_floor") or "0"),
            price_to=to_decimal(raw.get("price_to") or row.get("price_ceiling") or "0"),
            rungs=int(raw.get("rungs") or 0),
            window=int(raw.get("window") or 10),
        )
        status = ChaseStatus.of(row.get("status"))
        ledger = Ledger.from_row(row)
        self._state = LadderState(
            status=status,
            params=params,
            market_index=int(row.get("market_index") or 0),
            symbol=str(row.get("symbol") or ""),
            reduce_only=bool(row.get("reduce_only")),
            remaining=to_decimal(row.get("remaining") or "0"),
            filled=to_decimal(row.get("filled") or "0"),
            quote_action=str(row.get("quote_action") or Action.PAUSE.value),
            reason=row.get("reason"),
            rest_price=to_decimal(row["rest_price"]) if row.get("rest_price") is not None else None,
            rest_qty=to_decimal(row["rest_qty"]) if row.get("rest_qty") is not None else None,
            error=row.get("error"),
            algo_id=str(row.get("algo_id") or ""),
            created_at=int(row.get("created_at") or 0),
            ledger=ledger,
        )
        self._cois = {c.client_order_index for c in ledger.clips}
        self._reset_job()
        self._reconcile_master()

    async def start(
        self,
        *,
        algo_id: str,
        market_index: int,
        params: LadderParams,
        reduce_only: bool = False,
    ) -> None:
        meta = self._exec().get_market_by_index(market_index)
        if not meta:
            raise ValueError("Unknown market")
        ref = (params.price_from + params.price_to) / 2
        check_notional(params.qty, ref, settings.max_order_notional)
        self._state = LadderState(
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

    async def _place_rung(self, rung: Rung) -> bool:
        params = self._state.params
        if params is None:
            return False
        coi = self._next_coi()
        try:
            await self._exec().create_limit_order(
                market_index=self._state.market_index,
                side=params.side,
                size=fmt_decimal(rung.qty) or "0",
                price=fmt_decimal(rung.price) or "0",
                time_in_force="post_only",
                reduce_only=self._state.reduce_only,
                client_order_index=coi,
            )
        except Exception as e:
            # The venue's own refusal, so the blotter says why and not a guess.
            if is_min_size(e):
                self._place_refused = "below_min_qty"
                return False
            if is_would_cross(e):
                self._place_refused = "would_cross"
                return False
            if self._handle_tx_err(e):
                return False
            raise
        self._place_refused = None
        self._last_tx_ms = common.now_ms()
        found = self._find_open(coi)
        idx = int(found["order_index"]) if found and found.get("order_index") else None
        self._state.ledger.place(
            client_order_index=coi,
            price=rung.price,
            qty=rung.qty,
            now=common.now_ms(),
            order_index=idx,
            side=params.side,
        )
        return True

    async def _evaluate(self) -> None:
        async with self._lock:
            if (
                self._stop.is_set()
                or self._state.status != ChaseStatus.RUNNING
                or not self._state.params
            ):
                return
            if not self._exec().enabled:
                self._state.status = ChaseStatus.ERROR
                self._state.error = "Trading not configured"
                self._publish()
                return

            await self._sync_fills()
            self._reconcile_master()
            min_qty = self._clip_min_qty()
            if self._state.remaining <= 0 or leftover_is_dust(self._state.remaining, min_qty):
                await self._finish_done()
                return

            now = common.now_ms()
            if self._unproven_retry_at:
                if self._state.ledger.live_clips():
                    self._unproven_retry_at = 0
                elif now < self._unproven_retry_at:
                    self._state.quote_action = Action.PAUSE.value
                    if self._state.reason != "trades_reconcile_failed":
                        self._state.reason = "unproven_missing_clip"
                    self._state.rest_price = None
                    self._state.rest_qty = None
                    self._publish()
                    return

            if not self._exec().is_book_synced(self._state.market_index):
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "book_unsynced"
                self._sync_rest_from_live()
                self._publish()
                return

            if not self._account_ready():
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "account_unsynced"
                self._sync_rest_from_live()
                self._publish()
                return

            view = self._market_view()
            if view is None:
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = "no_market"
                self._sync_rest_from_live()
                self._publish()
                return

            ladder_params = self._state.params
            assert ladder_params is not None
            for clip in list(self._state.ledger.live_clips()):
                if self._working_crosses(clip.price, view, ladder_params.side):
                    await self._cancel_clip(clip)

            if now < self._backoff_until:
                self._state.quote_action = Action.PAUSE.value
                self._state.reason = self._backoff_reason or "rate_limited"
                self._sync_rest_from_live()
                self._publish()
                return

            live = self._state.ledger.live_clips()
            to_place = select_rungs_to_place(
                ladder_params,
                ledger=self._state.ledger,
                live_count=len(live),
                bid=view.bid,
                ask=view.ask,
            )
            placed_any = False
            self._place_refused = None
            for rung in to_place:
                now = common.now_ms()
                if now < self._backoff_until:
                    break
                if self._last_tx_ms > 0 and now - self._last_tx_ms < MIN_PLACE_GAP_MS:
                    break
                if await self._place_rung(rung):
                    placed_any = True

            self._sync_rest_from_live()
            live = self._state.ledger.live_clips()
            if live:
                self._state.quote_action = Action.REST.value
                self._state.reason = None
            elif not placed_any:
                self._state.quote_action = Action.PAUSE.value
                if self._place_refused:
                    self._state.reason = self._place_refused
                elif not self._state.reason:
                    self._state.reason = "waiting"

            if (
                self._state.remaining <= 0 or leftover_is_dust(self._state.remaining, min_qty)
            ) and not self._state.ledger.live_clips():
                await self._finish_done()
                return

            self._publish()
