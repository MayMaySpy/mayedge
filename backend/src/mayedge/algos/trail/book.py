"""Trail book. Rules in docs/trail-rules.md.

``venue`` stays in ``mayedge.algos.planner``. Trail's start checks use the same
market context and ticket list Planner does, and moving that module would only
rename the import.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.clip_book import WatchBook
from mayedge.algos.planner import venue
from mayedge.algos.trail.config import (
    MARKET_AMENDS_PER_MIN,
    MAX_PER_MARKET,
    TRAIL_COI_BASE,
    TRAIL_COI_END,
)
from mayedge.algos.trail.job import TrailRunner
from mayedge.algos.trail.plan import ALGO_ID, KIND_NAMES, TrailParams, TrailRefused, check_start
from mayedge.lighter.orders import protect_role_kind

logger = logging.getLogger(__name__)

MarketConflictFn = Callable[[int], bool]


def stop_tickets(ex: ChaseExecution, market_index: int, side: str) -> list[dict[str, Any]]:
    """TS4: the Market's Stop Tickets on the closing side. Take Profits stay."""
    out: list[dict[str, Any]] = []
    for o in venue.ticket_protects(ex, market_index):
        parsed = protect_role_kind(str(o.get("order_type") or ""))
        if parsed is None or parsed[0] != "sl":
            continue
        if str(o.get("side") or "") not in ("", side):
            continue
        out.append(o)
    return out


class TrailBook(WatchBook[TrailRunner]):
    ALGO_ID = ALGO_ID
    ID_PREFIX = "TR-"
    LABEL = "Trail"
    AMENDS_PER_MIN = MARKET_AMENDS_PER_MIN
    COI_BASE = TRAIL_COI_BASE
    COI_END = TRAIL_COI_END

    def _new_runner(self) -> TrailRunner:
        return TrailRunner(self)

    def stop_live_on_market(self, market_index: int) -> bool:
        """TS4: the Stop editor refuses a new Stop beside a Trail Stop."""
        return any(job.kind == "stop" for job in self._live(market_index, None))

    def _wants_prints(self, job: TrailRunner) -> bool:
        """F9: a Trail on Last needs every print on its Market."""
        p = job.state.params
        return p is not None and p.reference == "last"

    def _check_free(self, market_index: int, params: TrailParams) -> None:
        """S1 and S2."""
        if self._market_conflict and self._market_conflict(market_index):
            raise TrailRefused("S1", "A Planner or Grid runs this Market's orders")
        same = [job for job in self._live(market_index, None) if job.kind == params.kind]
        cap = MAX_PER_MARKET[params.kind]
        if len(same) >= cap:
            name = KIND_NAMES[params.kind]
            raise TrailRefused("S2", f"{cap} {name} already running on this Market")

    def preview_from_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """What start would send, and the Stop Tickets it would cancel. Sends nothing."""
        market_index = int(body["market_index"])
        params = TrailParams.from_json(body)
        ex = self.execution()
        ctx, _ = venue.market_context(ex, market_index)
        out: dict[str, Any] = {"resolved": None, "refused": None, "replaces": []}
        try:
            self._check_free(market_index, params)
            resolved = check_start(params, ctx)
            out["resolved"] = resolved.to_json()
            if params.kind == "stop":
                out["replaces"] = stop_tickets(ex, market_index, resolved.side)
        except TrailRefused as e:
            out["refused"] = e.to_dict()
        return out

    async def start_from_body(self, body: dict[str, Any]) -> None:
        market_index = int(body["market_index"])
        params = TrailParams.from_json(body)
        self._check_free(market_index, params)
        ex = self.execution()
        ctx, symbol = venue.market_context(ex, market_index)
        resolved = check_start(params, ctx)
        params.side = resolved.side
        replaced = stop_tickets(ex, market_index, resolved.side) if params.kind == "stop" else []
        algo_id = self.alloc_id()
        job = self._new_runner()
        self._jobs[algo_id] = job
        try:
            await job.start(
                algo_id=algo_id,
                market_index=market_index,
                symbol=symbol,
                params=params,
                resolved=resolved,
                replaced=replaced,
            )
        except Exception:
            _ = self._jobs.pop(algo_id, None)
            raise
        self._sync_watch(market_index)
        self.publish()

    async def edit_from_body(self, body: dict[str, Any]) -> None:
        algo_id = str(body.get("algo_id") or "")
        job = self._jobs.get(algo_id)
        if job is None:
            raise ValueError(f"unknown algo_id {algo_id}")
        await job.edit(TrailParams.from_json(body))

    async def stop(self, algo_id: str | None = None, *, keep_stop: bool = False) -> None:
        if algo_id:
            job = self._jobs.get(algo_id)
            if job:
                await job.stop(keep_stop=keep_stop)
            return
        await super().stop()
