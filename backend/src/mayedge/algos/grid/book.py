from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from mayedge import db as store
from mayedge import feed_health
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.grid.config import (
    GRID_COI_BASE,
    GRID_COI_END,
    HISTORY_CAP,
    RESTORE_FEED_TIMEOUT_S,
)
from mayedge.algos.grid.decide import ALGO_ID, GridParams
from mayedge.algos.grid.job import GridRunner
from mayedge.numbers import fmt_decimal, parse_decimal

logger = logging.getLogger(__name__)

AlgoPayload = dict[str, object]
MarketConflictFn = Callable[[int], bool]


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


class ChaseGridBook:
    """One chase-grid job per market."""

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int | None = None,
        coi_end: int | None = None,
        missing_fill_grace_ms: int = 800,
        market_conflict: MarketConflictFn | None = None,
    ) -> None:
        self._execution_fn = execution
        self._broadcast_fn = broadcast
        self._coi_base = coi_base if coi_base is not None else GRID_COI_BASE
        self._coi_end = coi_end if coi_end is not None else GRID_COI_END
        self._missing_fill_grace_ms = missing_fill_grace_ms
        self._market_conflict = market_conflict
        self._jobs: dict[str, GridRunner] = {}
        self._archive: list[AlgoPayload] = []
        self._id_seq = 0
        self._coi_seq = 0

    def set_market_conflict(self, fn: MarketConflictFn) -> None:
        self._market_conflict = fn

    @property
    def algo_type(self) -> str:
        return ALGO_ID

    @property
    def missing_fill_grace_ms(self) -> int:
        return self._missing_fill_grace_ms

    def execution(self) -> ChaseExecution:
        return self._execution_fn()

    def has(self, algo_id: str) -> bool:
        return algo_id in self._jobs

    def live_on_market(self, market_index: int, *, exclude: str | None = None) -> bool:
        for job in self._jobs.values():
            if exclude and job.state.algo_id == exclude:
                continue
            if job.state.market_index == market_index and job.state.status in ACTIVE_STATUSES:
                return True
        return False

    def alloc_id(self) -> str:
        self._id_seq += 1
        store.save_counters(self._id_seq, self._coi_seq)
        return f"CG-{self._id_seq:04d}"

    def alloc_coi(self) -> int:
        self._coi_seq += 1
        coi = self._coi_base + self._coi_seq
        if coi >= self._coi_end:
            raise RuntimeError("Chase-grid client_order_index range exhausted")
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

    def _persist_job(self, job: GridRunner, *, archived: bool) -> None:
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
                    logger.exception("failed to persist chase-grid job %s", job.state.algo_id)
        self._broadcast_fn(self.to_dict())

    def finish(self, job: GridRunner) -> None:
        snap = job.snapshot()
        algo_id = job.state.algo_id
        _ = self._jobs.pop(algo_id, None)
        if algo_id:
            try:
                self._persist_job(job, archived=True)
            except Exception:
                logger.exception("failed to archive chase-grid job %s", algo_id)
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

    async def restore(self) -> None:
        store.init_db()
        counters = store.load_counters()
        self._id_seq = counters["id_seq"]
        self._coi_seq = counters["coi_seq"]
        self._archive = store.load_history(HISTORY_CAP, algo_type=ALGO_ID)

        rows = store.load_active_runs(algo_type=ALGO_ID)
        if not rows:
            self.publish()
            return

        market_indices: set[int] = set()
        restored: list[tuple[str, GridRunner]] = []
        for row in rows:
            algo_id = str(row.get("algo_id") or "")
            try:
                job = GridRunner(self)
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
                logger.exception("failed to restore chase-grid job %s", algo_id)
                _ = self._jobs.pop(algo_id, None)
                self._archive_broken_row(row)

        await self._wait_feeds_ready(market_indices)
        for algo_id, job in restored:
            if algo_id not in self._jobs:
                continue
            try:
                await job.resume()
            except Exception:
                logger.exception("failed to resume chase-grid job %s", algo_id)
                _ = self._jobs.pop(algo_id, None)
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
                    "qty": row.get("qty"),
                    "remaining": row.get("remaining"),
                    "filled": row.get("filled"),
                    "quote_action": row.get("quote_action"),
                    "reason": row.get("reason"),
                    "created_at": row.get("created_at") or 0,
                    "error": "restore failed",
                    "params_json": row.get("params_json") or {},
                    "algo_type": ALGO_ID,
                },
                next_clip=_as_int(row.get("next_clip"), 1),
                next_fill=_as_int(row.get("next_fill"), 1),
                trade_ids=_as_int_set(row.get("trade_ids")),
                trade_qty_by_clip=_as_int_str_map(row.get("trade_qty_by_clip")),
                clips=_as_record_list(row.get("clips")),
                fills=_as_record_list(row.get("fills")),
                archived=True,
            )
        except Exception:
            logger.exception("failed to archive broken chase-grid job %s", algo_id)

    async def drain_for_shutdown(self) -> None:
        for job in list(self._jobs.values()):
            try:
                await job.drain_for_shutdown()
            except Exception:
                logger.exception("drain failed for %s", job.state.algo_id)

    async def pause_for_market(self, market_index: int | None) -> None:
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
        for job in list(self._jobs.values()):
            if job.state.algo_id:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("flush persist failed for %s", job.state.algo_id)
        store.save_counters(self._id_seq, self._coi_seq)

    async def start_from_body(self, body: dict[str, Any]) -> None:
        profit = body.get("profit_bps")
        if profit is None:
            raise ValueError("profit_bps is required")
        grid_bps = body.get("grid_bps", profit)
        params = GridParams(
            max_inventory=parse_decimal(str(body["qty"])),
            display_qty=parse_decimal(str(body["display_qty"])),
            offset_bps=parse_decimal(str(body.get("offset_bps", "4"))),
            profit_bps=parse_decimal(str(profit)),
            grid_bps=parse_decimal(str(grid_bps)),
            price_floor=parse_decimal(str(body["price_floor"])),
            price_ceiling=parse_decimal(str(body["price_ceiling"])),
            be_delay_ms=int(body.get("be_delay_ms") or 0),
        )
        await self.start(market_index=int(body["market_index"]), params=params)

    async def start(self, *, market_index: int, params: GridParams) -> None:
        ex = self.execution()
        if ex.ensure_book:
            ok = await ex.ensure_book(market_index)
            if ok is False:
                raise ValueError("Order book not synced")
        if self.live_on_market(market_index):
            raise ValueError(f"Chase-grid already running on market {market_index}")
        if self._market_conflict and self._market_conflict(market_index):
            raise ValueError(f"Another desk algo is already running on market {market_index}")
        algo_id = self.alloc_id()
        job = GridRunner(self)
        self._jobs[algo_id] = job
        try:
            await job.start(algo_id=algo_id, market_index=market_index, params=params)
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
