"""Planner book: one Planner per Market. Rules in docs/planner-rules.md."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from mayedge import db as store
from mayedge import feed_health
from mayedge.algos.chase.config import HISTORY_CAP, RESTORE_FEED_TIMEOUT_S
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.planner import venue
from mayedge.algos.planner.config import PLANNER_COI_BASE, PLANNER_COI_END
from mayedge.algos.planner.job import PlannerRunner
from mayedge.algos.planner.plan import ALGO_ID, PlannerParams, PlanRefused, build_plan
from mayedge.algos.trail.config import MARKET_AMENDS_PER_MIN

logger = logging.getLogger(__name__)

AlgoPayload = dict[str, object]
MarketConflictFn = Callable[[int], bool]


class PlannerBook:
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
        self._watch_prints = watch_prints
        self._amends: dict[int, deque[int]] = {}
        self._execution_fn = execution
        self._broadcast_fn = broadcast
        self._coi_base = coi_base
        self._coi_end = coi_end
        self._market_conflict = market_conflict
        self._jobs: dict[str, PlannerRunner] = {}
        self._archive: list[AlgoPayload] = []
        self._id_seq = 0
        self._coi_seq = 0

    def set_market_conflict(self, fn: MarketConflictFn) -> None:
        self._market_conflict = fn

    def set_watch_prints(self, fn: Callable[[int, bool], None]) -> None:
        self._watch_prints = fn

    def take_amend(self, market_index: int, now_ms: int) -> bool:
        """Trail F7: a Planner's trailing parts share one Amend budget a minute."""
        sent = self._amends.setdefault(market_index, deque())
        while sent and now_ms - sent[0] >= 60_000:
            sent.popleft()
        if len(sent) >= MARKET_AMENDS_PER_MIN:
            return False
        sent.append(now_ms)
        return True

    def _sync_watch(self, market_index: int) -> None:
        """Trail F9: keep a Market's prints while a plan there trails on Last."""
        if self._watch_prints is None:
            return
        want = any(
            j.state.params is not None
            and j.state.params.reference == "last"
            and j.state.params.trails()
            and j.state.status in ACTIVE_STATUSES
            for j in self._jobs.values()
            if j.state.market_index == market_index
        )
        self._watch_prints(market_index, want)

    @property
    def algo_type(self) -> str:
        return ALGO_ID

    def execution(self) -> ChaseExecution:
        return self._execution_fn()

    def has(self, algo_id: str) -> bool:
        return algo_id in self._jobs

    def live_on_market(self, market_index: int, *, exclude: str | None = None) -> bool:
        return self._live_job(market_index, exclude=exclude) is not None

    def _live_job(self, market_index: int, *, exclude: str | None = None) -> PlannerRunner | None:
        for job in self._jobs.values():
            st = job.state
            if exclude and st.algo_id == exclude:
                continue
            if st.market_index == market_index and st.status in ACTIVE_STATUSES:
                return job
        return None

    def _save_counters(self) -> None:
        store.save_book_counters(ALGO_ID, self._id_seq, self._coi_seq)

    def alloc_id(self) -> str:
        self._id_seq += 1
        self._save_counters()
        return f"PL-{self._id_seq:04d}"

    def alloc_coi(self) -> int:
        self._coi_seq += 1
        coi = self._coi_base + self._coi_seq
        if coi >= self._coi_end:
            raise RuntimeError("Planner client_order_index range exhausted")
        self._save_counters()
        return coi

    def to_dict(self) -> AlgoPayload:
        working = [
            job.snapshot() for job in self._jobs.values() if job.state.status in ACTIVE_STATUSES
        ]
        working.sort(key=lambda s: int(s.get("created_at") or 0), reverse=True)
        return {"type": "algo", "id": ALGO_ID, "working": working, "history": list(self._archive)}

    def _persist(self, job: PlannerRunner, *, archived: bool) -> None:
        ledger = job.state.ledger.to_persist()
        store.upsert_run(
            job.snapshot(),
            next_clip=ledger["next_clip"],
            next_fill=ledger["next_fill"],
            trade_ids=ledger["trade_ids"],
            trade_qty_by_clip=ledger["trade_qty_by_clip"],
            clips=ledger["clips"],
            fills=ledger["fills"],
            archived=archived,
        )

    def publish(self) -> None:
        for job in self._jobs.values():
            if job.state.algo_id and job.state.status in ACTIVE_STATUSES:
                try:
                    self._persist(job, archived=False)
                except Exception:
                    logger.exception("failed to persist planner %s", job.state.algo_id)
        self._broadcast_fn(self.to_dict())

    def finish(self, job: PlannerRunner) -> None:
        algo_id = job.state.algo_id
        _ = self._jobs.pop(algo_id, None)
        if algo_id:
            try:
                self._persist(job, archived=True)
            except Exception:
                logger.exception("failed to archive planner %s", algo_id)
            self._archive = [a for a in self._archive if a.get("algo_id") != algo_id]
            self._archive.insert(0, job.snapshot())
            self._archive = self._archive[:HISTORY_CAP]
        self._sync_watch(job.state.market_index)
        self.publish()

    def on_gateway(self, msg: AlgoPayload) -> None:
        for job in list(self._jobs.values()):
            job.on_gateway(msg)

    # ── start ────────────────────────────────────────────────────────────

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
        job = PlannerRunner(self)
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

    # ── lifecycle ────────────────────────────────────────────────────────

    async def stop(self, algo_id: str | None = None) -> None:
        if algo_id:
            job = self._jobs.get(algo_id)
            if job:
                await job.stop()
            return
        failed: Exception | None = None
        for job in list(self._jobs.values()):
            try:
                await job.stop()
            except Exception as e:
                logger.exception("stop failed for %s", job.state.algo_id)
                failed = failed or e
        if failed is not None:
            raise failed

    async def pause(self, algo_id: str) -> None:
        job = self._jobs.get(algo_id)
        if not job:
            raise ValueError(f"unknown algo_id {algo_id}")
        await job.pause()

    async def unpause(self, algo_id: str) -> None:
        job = self._jobs.get(algo_id)
        if not job:
            raise ValueError(f"unknown algo_id {algo_id}")
        await job.unpause()

    async def pause_for_market(self, market_index: int | None) -> None:
        """N2: Cancel all is about to take Planner's orders, so Planner stops first."""
        for job in list(self._jobs.values()):
            if market_index is not None and job.state.market_index != market_index:
                continue
            try:
                await job.stop()
            except Exception:
                logger.exception("planner stop for cancel-all failed for %s", job.state.algo_id)

    async def drain_for_shutdown(self) -> None:
        for job in list(self._jobs.values()):
            try:
                await job.drain_for_shutdown()
            except Exception:
                logger.exception("drain failed for %s", job.state.algo_id)

    async def flush(self) -> None:
        for job in list(self._jobs.values()):
            if job.state.algo_id:
                try:
                    self._persist(job, archived=False)
                except Exception:
                    logger.exception("flush persist failed for %s", job.state.algo_id)
        self._save_counters()

    async def _wait_feeds_ready(self) -> None:
        deadline = time.monotonic() + RESTORE_FEED_TIMEOUT_S
        while time.monotonic() < deadline:
            if feed_health.snapshot().get("account_ws") == "live" and self.execution().orders_hydrated():
                return
            await asyncio.sleep(0.1)
        logger.warning("planner restore: account feed not ready within %.0fs", RESTORE_FEED_TIMEOUT_S)

    async def restore(self) -> None:
        store.init_db()
        counters = store.load_book_counters(ALGO_ID)
        self._id_seq = counters["id_seq"]
        self._coi_seq = counters["coi_seq"]
        self._archive = store.load_history(HISTORY_CAP, algo_type=ALGO_ID)
        rows = store.load_active_runs(algo_type=ALGO_ID)
        if not rows:
            self.publish()
            return
        restored: list[PlannerRunner] = []
        for row in rows:
            algo_id = str(row.get("algo_id") or "")
            job = PlannerRunner(self)
            try:
                job.hydrate_from_row(row)
            except Exception:
                logger.exception("failed to restore planner %s, archiving it", algo_id)
                self._archive_broken(row)
                continue
            self._jobs[algo_id] = job
            restored.append(job)
        await self._wait_feeds_ready()
        for job in restored:
            self._sync_watch(job.state.market_index)
            try:
                await job.resume()
            except Exception:
                # Its stop is still on the venue. Leave the job up, in error, for the operator.
                logger.exception("failed to resume planner %s", job.state.algo_id)
                job.state.status = ChaseStatus.ERROR
                job.state.error = "restore failed"
        self.publish()

    def _archive_broken(self, row: dict[str, Any]) -> None:
        try:
            store.upsert_run(
                {
                    "algo_id": row.get("algo_id"),
                    "algo_type": ALGO_ID,
                    "status": ChaseStatus.STOPPED.value,
                    "market_index": row.get("market_index") or 0,
                    "symbol": row.get("symbol") or "",
                    "side": row.get("side"),
                    "qty": row.get("qty"),
                    "filled": row.get("filled"),
                    "created_at": row.get("created_at") or 0,
                    "error": "restore failed",
                    "params_json": row.get("params_json") or {},
                },
                next_clip=int(row.get("next_clip") or 1),
                next_fill=int(row.get("next_fill") or 1),
                trade_ids=set(row.get("trade_ids") or set()),
                trade_qty_by_clip=dict(row.get("trade_qty_by_clip") or {}),
                clips=list(row.get("clips") or []),
                fills=list(row.get("fills") or []),
                archived=True,
            )
        except Exception:
            logger.exception("failed to archive broken planner %s", row.get("algo_id"))
