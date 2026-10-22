"""Planner book: one Planner per Market. Rules in docs/planner-rules.md."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.clip_book import AlgoBook, AlgoPayload, MarketWatch
from mayedge.algos.planner import venue
from mayedge.algos.planner.config import (
    MARKET_AMENDS_PER_MIN,
    PLANNER_COI_BASE,
    PLANNER_COI_END,
)
from mayedge.algos.planner.job import PlannerRunner
from mayedge.algos.planner.plan import ALGO_ID, PlannerParams, PlanRefused, build_plan
from mayedge.algos.planner.state import PlannerState
from mayedge.rows import obj

logger = logging.getLogger(__name__)

MarketConflictFn = Callable[[int], bool]


class PlannerBook(AlgoBook[PlannerRunner], MarketWatch):
    ALGO_ID = ALGO_ID
    ID_PREFIX = "PL-"
    LABEL = "Planner"
    AMENDS_PER_MIN = MARKET_AMENDS_PER_MIN
    COI_BASE = PLANNER_COI_BASE
    COI_END = PLANNER_COI_END
    RESTORE_WAITS_FOR_FEEDS = False

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int = PLANNER_COI_BASE,
        coi_end: int = PLANNER_COI_END,
        market_conflict: MarketConflictFn | None = None,
        watch_prints: Callable[[int, bool], None] | None = None,
    ) -> None:
        super().__init__(
            execution=execution, broadcast=broadcast, coi_base=coi_base, coi_end=coi_end
        )
        MarketWatch.__init__(self, market_conflict, watch_prints)

    def _new_runner(self) -> PlannerRunner:
        return PlannerRunner(self)

    def _view(self, job: PlannerRunner) -> PlannerState:
        return job.state

    def _seeds_counters(self) -> bool:
        return False

    def _log_empty_restore(self) -> bool:
        return False

    def _restore_waits_for_account(self) -> bool:
        return True

    def _wait_with_nothing_restored(self) -> bool:
        return True

    def _cancel_all_stops(self) -> bool:
        return True

    def _remember_broken(self) -> bool:
        return False

    def _on_restored(self, job: PlannerRunner) -> None:
        self._sync_watch(job.state.market_index)

    def _on_finished(self, job: PlannerRunner) -> None:
        self._sync_watch(job.state.market_index)

    def _resume_failed(self, job: PlannerRunner, row: Mapping[str, object]) -> None:
        del row
        # Its stop is still on the venue. Leave the job up, in error, for the operator.
        logger.exception("failed to resume planner %s", job.state.algo_id)
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
            "filled": row.get("filled"),
            "created_at": row.get("created_at") or 0,
            "error": "restore failed",
            "params_json": obj(row.get("params_json")),
        }

    def _sync_watch(self, market_index: int) -> None:
        """Keep a Market's prints while a plan there trails on Last."""
        if self._watch_prints is None:
            return
        want = any(
            job.state.params is not None
            and job.state.params.reference == "last"
            and job.state.params.trails()
            for job in self._live(market_index, None)
        )
        self._watch_prints(market_index, want)

    def _check_free(self, market_index: int) -> None:
        """S5: one Planner per Market, alone among desk algos."""
        if self.live_on_market(market_index):
            raise PlanRefused("S5", "A Planner is already running on this Market")
        if self._market_conflict and self._market_conflict(market_index):
            raise PlanRefused("S5", "Another desk algo is running on this Market")

    def preview_from_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """The plan start would send, and what Attach would cancel. Sends nothing."""
        market_index = int(body["market_index"])
        params = PlannerParams.from_json(body)
        ex = self.execution()
        ctx, _ = venue.market_context(ex, market_index)
        out: dict[str, Any] = {
            "plan": None,
            "refused": None,
            "replaces": [],
            "equity": str(ctx.equity) if ctx.equity is not None else None,
            "mark": str(ctx.mark),
        }
        try:
            self._check_free(market_index)
            out["plan"] = build_plan(params, ctx).to_json()
        except PlanRefused as e:
            out["refused"] = e.to_dict()
        if params.mode == "attach":
            out["replaces"] = venue.ticket_protects(ex, market_index)
        return out

    async def start_from_body(self, body: dict[str, Any]) -> None:
        market_index = int(body["market_index"])
        params = PlannerParams.from_json(body)
        self._check_free(market_index)
        ex = self.execution()
        ctx, symbol = venue.market_context(ex, market_index)
        plan = build_plan(params, ctx)
        replaced = venue.ticket_protects(ex, market_index) if params.mode == "attach" else []
        algo_id = self.alloc_id()
        job = self._new_runner()
        self._jobs[algo_id] = job
        try:
            await job.start(
                algo_id=algo_id,
                market_index=market_index,
                symbol=symbol,
                params=params,
                plan=plan,
                replaced=replaced,
            )
        except Exception:
            _ = self._jobs.pop(algo_id, None)
            raise
        self._sync_watch(market_index)
        self.publish()

    async def replan_from_body(self, body: dict[str, Any]) -> None:
        algo_id = str(body.get("algo_id") or "")
        job = self._jobs.get(algo_id)
        if job is None:
            raise ValueError(f"unknown algo_id {algo_id}")
        await job.replan(PlannerParams.from_json(body))
        self._sync_watch(job.state.market_index)

    async def finish_entry(self, algo_id: str) -> None:
        """E14: Protect now."""
        job = self._jobs.get(algo_id)
        if job is None:
            raise ValueError(f"unknown algo_id {algo_id}")
        await job.finish_entry()
        self._sync_watch(job.state.market_index)

    async def stop(self, algo_id: str | None = None) -> None:
        if algo_id:
            job = self._jobs.get(algo_id)
            if job:
                await job.stop()
            return
        await super().stop()
