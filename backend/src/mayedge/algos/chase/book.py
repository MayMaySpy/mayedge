from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from typing import cast

from mayedge import feed_health
from mayedge import db as store
from mayedge.algos.chase.config import (
    CHASE_COI_BASE,
    CHASE_COI_END,
    HISTORY_CAP,
    RESTORE_FEED_TIMEOUT_S,
)
from mayedge.algos.chase.iceberg import ALGO_ID, ChaseIcebergParams
from mayedge.algos.chase.job import ChaseIcebergRunner
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.numbers import fmt_decimal
from mayedge.algos.chase.execution import ChaseExecution

logger = logging.getLogger(__name__)

AlgoPayload = dict[str, object]


def _as_int(raw: object, default: int = 0) -> int:
    if isinstance(raw, bool) or raw is None:
        return default
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw:
        try:
            return int(raw)
        except ValueError:
            return default
    return default


def _as_int_set(raw: object) -> set[int]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        return set()
    return {int(str(x)) for x in raw}


def _as_int_str_map(raw: object) -> dict[int, str]:
    if not isinstance(raw, dict):
        return {}
    items = cast(dict[object, object], raw)
    return {int(str(k)): str(v) for k, v in items.items()}


def _as_record_list(raw: object) -> list[AlgoPayload]:
    if not isinstance(raw, list):
        return []
    out: list[AlgoPayload] = []
    for item in cast("list[object]", raw):
        if isinstance(item, dict):
            out.append(cast(AlgoPayload, item))
    return out


def _created_at(snap: Mapping[str, object]) -> int:
    return _as_int(snap.get("created_at"))


class ChaseBook:
    """Many chase jobs. Start does not replace a live one."""

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int | None = None,
        coi_end: int | None = None,
        missing_fill_grace_ms: int = 800,
    ) -> None:
        self._execution_fn: Callable[[], ChaseExecution] = execution
        self._broadcast_fn: Callable[[AlgoPayload], None] = broadcast
        self._coi_base: int = coi_base if coi_base is not None else CHASE_COI_BASE
        self._coi_end: int = coi_end if coi_end is not None else CHASE_COI_END
        self._missing_fill_grace_ms: int = missing_fill_grace_ms
        self._jobs: dict[str, ChaseIcebergRunner] = {}
        self._archive: list[AlgoPayload] = []
        self._id_seq: int = 0
        self._coi_seq: int = 0

    @property
    def missing_fill_grace_ms(self) -> int:
        return self._missing_fill_grace_ms

    def execution(self) -> ChaseExecution:
        return self._execution_fn()

    def live_on_market(self, market_index: int, *, exclude: str | None = None) -> bool:
        for job in self._jobs.values():
            if exclude and job.state.algo_id == exclude:
                continue
            if job.state.market_index == market_index and job.state.status in ACTIVE_STATUSES:
                return True
        return False

    def live_on_market_side(
        self, market_index: int, side: str, *, exclude: str | None = None
    ) -> bool:
        for job in self._jobs.values():
            if exclude and job.state.algo_id == exclude:
                continue
            if job.state.market_index != market_index:
                continue
            if job.state.status not in ACTIVE_STATUSES:
                continue
            params = job.state.params
            if params and params.side == side:
                return True
        return False

    def alloc_id(self) -> str:
        self._id_seq += 1
        store.save_counters(self._id_seq, self._coi_seq)
        return f"CH-{self._id_seq:04d}"

    def alloc_coi(self) -> int:
        self._coi_seq += 1
        coi = self._coi_base + self._coi_seq
        if coi >= self._coi_end:
            raise RuntimeError("Chase client_order_index range exhausted")
        store.save_counters(self._id_seq, self._coi_seq)
        return coi

    def to_dict(self) -> AlgoPayload:
        working = [
            job.snapshot() for job in self._jobs.values() if job.state.status in ACTIVE_STATUSES
        ]
        working.sort(key=_created_at, reverse=True)
        return {
            "type": "algo",
            "id": ALGO_ID,
            "working": working,
            "history": list(self._archive),
        }

    def _persist_job(self, job: ChaseIcebergRunner, *, archived: bool) -> None:
        snap = job.snapshot()
        ledger = job.state.ledger
        store.upsert_run(
            snap,
            next_clip=ledger.next_clip,
            next_fill=ledger.next_fill,
            trade_ids=set(ledger.trade_ids),
            trade_qty_by_clip={
                seq: (fmt_decimal(qty) or "0") for seq, qty in ledger.trade_qty_by_clip.items()
            },
            clips=[c.to_persist() for c in ledger.clips],
            fills=[f.to_persist() for f in ledger.fills],
            archived=archived,
        )

    def publish(self) -> None:
        for job in self._jobs.values():
            if job.state.algo_id and job.state.status in ACTIVE_STATUSES:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("failed to persist chase job %s", job.state.algo_id)
        payload = self.to_dict()
        self._broadcast_fn(payload)

    def finish(self, job: ChaseIcebergRunner) -> None:
        snap = job.snapshot()
        algo_id = job.state.algo_id
        _ = self._jobs.pop(algo_id, None)
        if algo_id:
            try:
                self._persist_job(job, archived=True)
            except Exception:
                logger.exception("failed to archive chase job %s", algo_id)
            self._archive = [a for a in self._archive if a.get("algo_id") != algo_id]
            self._archive.insert(0, snap)
            self._archive = self._archive[:HISTORY_CAP]
        self.publish()

    def on_gateway(self, msg: AlgoPayload) -> None:
        for job in list(self._jobs.values()):
            job.on_gateway(msg)

    async def _wait_feeds_ready(self, market_indices: set[int]) -> None:
        if not market_indices:
            return
        deadline = time.monotonic() + RESTORE_FEED_TIMEOUT_S
        while time.monotonic() < deadline:
            ex = self.execution()
            snap = feed_health.snapshot()
            if snap.get("account_ws") != "live":
                await asyncio.sleep(0.1)
                continue
            if not ex.orders_hydrated():
                await asyncio.sleep(0.1)
                continue
            if all(ex.is_book_synced(mi) for mi in market_indices):
                return
            await asyncio.sleep(0.1)
        logger.warning(
            "restore: feeds not ready within %.0fs for markets %s",
            RESTORE_FEED_TIMEOUT_S,
            sorted(market_indices),
        )

    async def restore(self) -> None:
        """Load counters, history, and auto-resume active jobs from SQLite."""
        store.init_db()
        counters = store.load_counters()
        self._id_seq = counters["id_seq"]
        self._coi_seq = counters["coi_seq"]
        self._archive = store.load_history(HISTORY_CAP, algo_type="chase-iceberg")

        rows = store.load_active_runs(algo_type="chase-iceberg")
        if not rows:
            logger.info("no active chase jobs to restore")
            self.publish()
            return

        market_indices: set[int] = set()
        restored: list[tuple[str, ChaseIcebergRunner]] = []
        for row in rows:
            algo_id = str(row.get("algo_id") or "")
            try:
                job = ChaseIcebergRunner(self)
                job.hydrate_from_row(row)
                self._jobs[algo_id] = job
                mi = int(row.get("market_index") or 0)
                if mi:
                    market_indices.add(mi)
                    ex = self.execution()
                    if ex.ensure_book:
                        await ex.ensure_book(mi)
                restored.append((algo_id, job))
            except Exception:
                logger.exception("failed to restore chase job %s — archiving as stopped", algo_id)
                _ = self._jobs.pop(algo_id, None)
                self._archive_broken_row(row)

        await self._wait_feeds_ready(market_indices)

        for algo_id, job in restored:
            if algo_id not in self._jobs:
                continue
            try:
                await job.resume()
            except Exception:
                logger.exception("failed to resume chase job %s — archiving as stopped", algo_id)
                _ = self._jobs.pop(algo_id, None)
                row = next((r for r in rows if str(r.get("algo_id")) == algo_id), {})
                self._archive_broken_row(row)
        self.publish()

    def _archive_broken_row(self, row: Mapping[str, object]) -> None:
        algo_id = str(row.get("algo_id") or "")
        try:
            store.upsert_run(
                {
                    "algo_id": algo_id,
                    "status": ChaseStatus.STOPPED.value,
                    "market_index": row.get("market_index") or 0,
                    "symbol": row.get("symbol") or "",
                    "reduce_only": row.get("reduce_only"),
                    "side": row.get("side"),
                    "qty": row.get("qty"),
                    "display_qty": row.get("display_qty"),
                    "offset_bps": row.get("offset_bps"),
                    "price_floor": row.get("price_floor"),
                    "price_ceiling": row.get("price_ceiling"),
                    "remaining": row.get("remaining"),
                    "filled": row.get("filled"),
                    "quote_action": row.get("quote_action"),
                    "reason": row.get("reason"),
                    "rest_price": row.get("rest_price"),
                    "rest_qty": row.get("rest_qty"),
                    "created_at": row.get("created_at") or 0,
                    "error": "restore failed",
                },
                next_clip=_as_int(row.get("next_clip"), 1),
                next_fill=_as_int(row.get("next_fill"), 1),
                trade_ids=_as_int_set(row.get("trade_ids")),
                trade_qty_by_clip=_as_int_str_map(row.get("trade_qty_by_clip")),
                clips=_as_record_list(row.get("clips")),
                fills=_as_record_list(row.get("fills")),
                archived=True,
            )
            snap = store.load_history(1)
            if snap and snap[0].get("algo_id") == algo_id:
                self._archive = [a for a in self._archive if a.get("algo_id") != algo_id]
                self._archive.insert(0, snap[0])
                self._archive = self._archive[:HISTORY_CAP]
        except Exception:
            logger.exception("failed to archive broken chase job %s", algo_id)

    async def drain_for_shutdown(self) -> None:
        """Pull all venue children before process exit."""
        for job in list(self._jobs.values()):
            try:
                await job.drain_for_shutdown()
            except Exception:
                logger.exception("drain failed for %s", job.state.algo_id)

    async def pause_for_market(self, market_index: int | None) -> None:
        """Pause RUNNING chase jobs on a market (or all) before venue cancel-all."""
        for job in list(self._jobs.values()):
            if job.state.status != ChaseStatus.RUNNING:
                continue
            if market_index is not None and job.state.market_index != market_index:
                continue
            try:
                await job.pause()
            except Exception:
                logger.exception("pause_for_market failed for %s", job.state.algo_id)

    async def flush(self) -> None:
        """Final write of all live jobs (e.g. before shutdown cancel)."""
        for job in list(self._jobs.values()):
            if job.state.algo_id:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("flush persist failed for %s", job.state.algo_id)
        store.save_counters(self._id_seq, self._coi_seq)

    async def start(
        self,
        *,
        market_index: int,
        params: ChaseIcebergParams,
        reduce_only: bool = False,
    ) -> None:
        ex = self.execution()
        if ex.ensure_book:
            ok = await ex.ensure_book(market_index)
            if ok is False:
                raise ValueError("Order book not synced")
        if self.live_on_market_side(market_index, params.side):
            raise ValueError(
                f"Chase already running on market {market_index} side {params.side}"
            )
        algo_id = self.alloc_id()
        job = ChaseIcebergRunner(self)
        self._jobs[algo_id] = job
        try:
            await job.start(
                algo_id=algo_id,
                market_index=market_index,
                params=params,
                reduce_only=reduce_only,
            )
        except Exception:
            _ = self._jobs.pop(algo_id, None)
            raise
        self.publish()

    async def stop(self, algo_id: str | None = None) -> None:
        if algo_id:
            job = self._jobs.get(algo_id)
            if job:
                await job.stop()
            else:
                self.publish()
            return
        for job in list(self._jobs.values()):
            await job.stop()

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
