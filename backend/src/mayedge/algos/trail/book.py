"""Trail book. Rules in docs/trail-rules.md."""

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
from mayedge.algos.trail.config import (
    MARKET_AMENDS_PER_MIN,
    MAX_PER_MARKET,
    TRAIL_COI_BASE,
    TRAIL_COI_END,
)
from mayedge.algos.trail.job import TrailRunner
from mayedge.algos.trail.plan import ALGO_ID, KIND_NAMES, TrailParams, TrailRefused, check_start
from mayedge.lighter.orders import protect_role_kind
from mayedge.rows import items, obj

logger = logging.getLogger(__name__)

AlgoPayload = dict[str, object]
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


class TrailBook:
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
        self._execution_fn = execution
        self._broadcast_fn = broadcast
        self._coi_base = coi_base
        self._coi_end = coi_end
        self._market_conflict = market_conflict
        self._watch_prints = watch_prints
        self._jobs: dict[str, TrailRunner] = {}
        self._archive: list[AlgoPayload] = []
        self._id_seq = 0
        self._coi_seq = 0
        self._amends: dict[int, deque[int]] = {}

    def set_market_conflict(self, fn: MarketConflictFn) -> None:
        self._market_conflict = fn

    def set_watch_prints(self, fn: Callable[[int, bool], None]) -> None:
        self._watch_prints = fn

    @property
    def algo_type(self) -> str:
        return ALGO_ID

    def execution(self) -> ChaseExecution:
        return self._execution_fn()

    def has(self, algo_id: str) -> bool:
        return algo_id in self._jobs

    def _live(self, market_index: int | None = None) -> list[TrailRunner]:
        return [
            j
            for j in self._jobs.values()
            if j.state.status in ACTIVE_STATUSES
            and (market_index is None or j.state.market_index == market_index)
        ]

    def live_on_market(self, market_index: int, *, exclude: str | None = None) -> bool:
        return any(j.state.algo_id != exclude for j in self._live(market_index))

    def stop_live_on_market(self, market_index: int) -> bool:
        """TS4: the Stop editor refuses a new Stop beside a Trail Stop."""
        return any(j.kind == "stop" for j in self._live(market_index))

    def take_amend(self, market_index: int, now_ms: int) -> bool:
        """F7: the Trails on one Market share one Amend budget a minute."""
        sent = self._amends.setdefault(market_index, deque())
        while sent and now_ms - sent[0] >= 60_000:
            sent.popleft()
        if len(sent) >= MARKET_AMENDS_PER_MIN:
            return False
        sent.append(now_ms)
        return True

    def _save_counters(self) -> None:
        store.save_book_counters(ALGO_ID, self._id_seq, self._coi_seq)

    def alloc_id(self) -> str:
        self._id_seq += 1
        self._save_counters()
        return f"TR-{self._id_seq:04d}"

    def alloc_coi(self) -> int:
        self._coi_seq += 1
        coi = self._coi_base + self._coi_seq
        if coi >= self._coi_end:
            raise RuntimeError("Trail client_order_index range exhausted")
        self._save_counters()
        return coi

    def to_dict(self) -> AlgoPayload:
        working = [job.snapshot() for job in self._live()]
        working.sort(key=lambda s: int(s.get("created_at") or 0), reverse=True)
        return {"type": "algo", "id": ALGO_ID, "working": working, "history": list(self._archive)}

    def _persist(self, job: TrailRunner, *, archived: bool) -> None:
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
        for job in self._live():
            if job.state.algo_id:
                try:
                    self._persist(job, archived=False)
                except Exception:
                    logger.exception("failed to persist trail %s", job.state.algo_id)
        self._broadcast_fn(self.to_dict())

    def _sync_watch(self, market_index: int) -> None:
        """F9: keep a Market's prints while a Trail on Last runs there."""
        if self._watch_prints is None:
            return
        want = any(
            j.state.params is not None and j.state.params.reference == "last"
            for j in self._live(market_index)
        )
        self._watch_prints(market_index, want)

    def finish(self, job: TrailRunner) -> None:
        algo_id = job.state.algo_id
        _ = self._jobs.pop(algo_id, None)
        if algo_id:
            try:
                self._persist(job, archived=True)
            except Exception:
                logger.exception("failed to archive trail %s", algo_id)
            self._archive = [a for a in self._archive if a.get("algo_id") != algo_id]
            self._archive.insert(0, job.snapshot())
            self._archive = self._archive[:HISTORY_CAP]
        self._sync_watch(job.state.market_index)
        self.publish()

    def on_gateway(self, msg: AlgoPayload) -> None:
        for job in list(self._jobs.values()):
            job.on_gateway(msg)

    # ── start ────────────────────────────────────────────────────────────

    def _check_free(self, market_index: int, params: TrailParams) -> None:
        """S1 and S2."""
        if self._market_conflict and self._market_conflict(market_index):
            raise TrailRefused("S1", "A Planner or Grid runs this Market's orders")
        same = [j for j in self._live(market_index) if j.kind == params.kind]
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
        job = TrailRunner(self)
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

    # ── lifecycle ────────────────────────────────────────────────────────

    async def stop(self, algo_id: str | None = None, *, keep_stop: bool = False) -> None:
        if algo_id:
            job = self._jobs.get(algo_id)
            if job:
                await job.stop(keep_stop=keep_stop)
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
        """S4: Cancel all is about to take the Trails' orders, so they stop first."""
        for job in list(self._jobs.values()):
            if market_index is not None and job.state.market_index != market_index:
                continue
            try:
                await job.stop()
            except Exception:
                logger.exception("trail stop for cancel-all failed for %s", job.state.algo_id)

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
            if (
                feed_health.snapshot().get("account_ws") == "live"
                and self.execution().orders_hydrated()
            ):
                return
            await asyncio.sleep(0.1)
        logger.warning("trail restore: account feed not ready within %.0fs", RESTORE_FEED_TIMEOUT_S)

    async def restore(self) -> None:
        store.init_db()
        counters = store.load_book_counters(ALGO_ID)
        self._id_seq = counters["id_seq"]
        self._coi_seq = counters["coi_seq"]
        self._archive = store.load_history(HISTORY_CAP, algo_type=ALGO_ID)
        rows = store.load_active_runs(algo_type=ALGO_ID)
        restored: list[TrailRunner] = []
        for row in rows:
            algo_id = str(row.get("algo_id") or "")
            job = TrailRunner(self)
            try:
                job.hydrate_from_row(row)
            except Exception:
                logger.exception("failed to restore trail %s, archiving it", algo_id)
                self._archive_broken(row)
                continue
            self._jobs[algo_id] = job
            restored.append(job)
        if restored:
            await self._wait_feeds_ready()
        for job in restored:
            self._sync_watch(job.state.market_index)
            try:
                await job.resume()
            except Exception:
                logger.exception("failed to resume trail %s", job.state.algo_id)
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
                    "created_at": row.get("created_at") or 0,
                    "error": "restore failed",
                    "params_json": obj(row.get("params_json")),
                },
                next_clip=int(row.get("next_clip") or 1),
                next_fill=int(row.get("next_fill") or 1),
                trade_ids=set(row.get("trade_ids") or set()),
                trade_qty_by_clip={
                    int(k): str(v) for k, v in obj(row.get("trade_qty_by_clip")).items()
                },
                clips=list(items(row.get("clips"))),
                fills=list(items(row.get("fills"))),
                archived=True,
            )
        except Exception:
            logger.exception("failed to archive broken trail %s", row.get("algo_id"))
