"""Planner book: one Planner per Market. Rules in docs/planner-rules.md."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mayedge.algos.clip_book import WatchBook
from mayedge.algos.planner import venue
from mayedge.algos.planner.config import (
    MARKET_AMENDS_PER_MIN,
    PLANNER_COI_BASE,
    PLANNER_COI_END,
)
from mayedge.algos.planner.job import PlannerRunner
from mayedge.algos.planner.plan import ALGO_ID, PlannerParams, PlanRefused, build_plan

logger = logging.getLogger(__name__)

MarketConflictFn = Callable[[int], bool]


class PlannerBook(WatchBook[PlannerRunner]):
    ALGO_ID = ALGO_ID
    ID_PREFIX = "PL-"
    LABEL = "Planner"
    BROKEN_KEEPS = ("side", "qty", "filled")
    AMENDS_PER_MIN = MARKET_AMENDS_PER_MIN
    COI_BASE = PLANNER_COI_BASE
    COI_END = PLANNER_COI_END

    def _new_runner(self) -> PlannerRunner:
        return PlannerRunner(self)

    def _wait_with_nothing_restored(self) -> bool:
        return True

    def _wants_prints(self, job: PlannerRunner) -> bool:
        """A plan that trails on Last needs every print on its Market."""
        p = job.state.params
        return p is not None and p.reference == "last" and p.trails()

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
