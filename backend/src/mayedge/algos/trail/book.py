"""Trail book. Rules in docs/trail-rules.md.

``venue`` stays in ``mayedge.algos.planner``. Trail's start checks use the same
market context and ticket list Planner does, and moving that module would only
rename the import.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.clip_book import AlgoBook, AlgoPayload
from mayedge.algos.planner import venue
from mayedge.algos.trail.config import (
    MARKET_AMENDS_PER_MIN,
    MAX_PER_MARKET,
    TRAIL_COI_BASE,
    TRAIL_COI_END,
)
from mayedge.algos.trail.job import TrailRunner
from mayedge.algos.trail.plan import ALGO_ID, KIND_NAMES, TrailParams, TrailRefused, check_start
from mayedge.algos.trail.state import TrailState
from mayedge.lighter.orders import protect_role_kind
from mayedge.rows import obj

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


class TrailBook(AlgoBook[TrailRunner]):
    ALGO_ID = ALGO_ID
    ID_PREFIX = "TR-"
    LABEL = "Trail"
    COI_BASE = TRAIL_COI_BASE
    COI_END = TRAIL_COI_END
    RESTORE_WAITS_FOR_FEEDS = False

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int = TRAIL_COI_BASE,
        coi_end: int = TRAIL_COI_END,
        market_conflict: MarketConflictFn | None = None,
        watch_prints: Callable[[int, bool], None] | None = None,
    ) -> None:
        super().__init__(
            execution=execution, broadcast=broadcast, coi_base=coi_base, coi_end=coi_end
        )
        self._market_conflict = market_conflict
        self._watch_prints = watch_prints
        self._amends: dict[int, deque[int]] = {}

    def _new_runner(self) -> TrailRunner:
        return TrailRunner(self)

    def _view(self, job: TrailRunner) -> TrailState:
        return job.state

    def _seeds_counters(self) -> bool:
        return False

    def _log_empty_restore(self) -> bool:
        return False

    def _restore_waits_for_account(self) -> bool:
        return True

    def _cancel_all_stops(self) -> bool:
        return True

    def _remember_broken(self) -> bool:
        return False

    def _on_restored(self, job: TrailRunner) -> None:
        self._sync_watch(job.state.market_index)

    def _on_finished(self, job: TrailRunner) -> None:
        self._sync_watch(job.state.market_index)

    def _resume_failed(self, job: TrailRunner, row: Mapping[str, object]) -> None:
        del row
        logger.exception("failed to resume trail %s", job.state.algo_id)
        job.state.status = ChaseStatus.ERROR
        job.state.error = "restore failed"

    def _broken_run(self, row: Mapping[str, object]) -> dict[str, Any]:
        return {
            "algo_id": row.get("algo_id"),
            "algo_type": self.ALGO_ID,
            "status": ChaseStatus.STOPPED.value,
            "market_index": row.get("market_index") or 0,
            "symbol": row.get("symbol") or "",
            "side": row.get("side"),
            "qty": row.get("qty"),
            "created_at": row.get("created_at") or 0,
            "error": "restore failed",
            "params_json": obj(row.get("params_json")),
        }

    def set_market_conflict(self, fn: MarketConflictFn) -> None:
        self._market_conflict = fn

    def set_watch_prints(self, fn: Callable[[int, bool], None]) -> None:
        self._watch_prints = fn

    def stop_live_on_market(self, market_index: int) -> bool:
        """TS4: the Stop editor refuses a new Stop beside a Trail Stop."""
        return any(job.kind == "stop" for job in self._live(market_index, None))

    def take_amend(self, market_index: int, now_ms: int) -> bool:
        """F7: the Trails on one Market share one Amend budget a minute."""
        sent = self._amends.setdefault(market_index, deque())
        while sent and now_ms - sent[0] >= 60_000:
            sent.popleft()
        if len(sent) >= MARKET_AMENDS_PER_MIN:
            return False
        sent.append(now_ms)
        return True

    def _sync_watch(self, market_index: int) -> None:
        """F9: keep a Market's prints while a Trail on Last runs there."""
        if self._watch_prints is None:
            return
        want = any(
            job.state.params is not None and job.state.params.reference == "last"
            for job in self._live(market_index, None)
        )
        self._watch_prints(market_index, want)

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
