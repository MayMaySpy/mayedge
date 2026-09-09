from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from typing import cast

from mayedge import db as store
from mayedge.algos.chase.config import HISTORY_CAP
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.twap.job import AdvancedTwapRunner
from mayedge.algos.twap.plan import ALGO_ID, TWAP_COI_BASE, TWAP_COI_END, AdvancedTwapParams
from mayedge.numbers import fmt_decimal

logger = logging.getLogger(__name__)

AlgoPayload = dict[str, object]
_TW_ID = re.compile(r"^TW-(\d+)$")


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


class AdvancedTwapBook:
    """Many advanced-TWAP jobs. Native exchange TWAP does not live here."""

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int | None = None,
        coi_end: int | None = None,
    ) -> None:
        self._execution_fn = execution
        self._broadcast_fn = broadcast
        self._coi_base = coi_base if coi_base is not None else TWAP_COI_BASE
        self._coi_end = coi_end if coi_end is not None else TWAP_COI_END
        self._jobs: dict[str, AdvancedTwapRunner] = {}
        self._archive: list[AlgoPayload] = []
        self._id_seq = 0
        self._coi_seq = 0

    def execution(self) -> ChaseExecution:
        return self._execution_fn()

    def has(self, algo_id: str) -> bool:
        return algo_id in self._jobs

    def alloc_id(self) -> str:
        self._id_seq += 1
        return f"TW-{self._id_seq:04d}"

    def alloc_coi(self) -> int:
        self._coi_seq += 1
        coi = self._coi_base + self._coi_seq
        if coi >= self._coi_end:
            raise RuntimeError("TWAP client_order_index range exhausted")
        return coi

    def to_dict(self) -> AlgoPayload:
        working = [job.snapshot() for job in self._jobs.values() if job.status in ACTIVE_STATUSES]
        working.sort(key=_created_at, reverse=True)
        return {
            "type": "algo",
            "id": ALGO_ID,
            "working": working,
            "history": list(self._archive),
        }

    def _persist_job(self, job: AdvancedTwapRunner, *, archived: bool) -> None:
        snap = job.snapshot()
        ledger = job.ledger
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
            if job.algo_id and job.status in ACTIVE_STATUSES:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("failed to persist twap job %s", job.algo_id)
        self._broadcast_fn(self.to_dict())

    def finish(self, job: AdvancedTwapRunner) -> None:
        snap = job.snapshot()
        algo_id = job.algo_id
        _ = self._jobs.pop(algo_id, None)
        if algo_id:
            try:
                self._persist_job(job, archived=True)
            except Exception:
                logger.exception("failed to archive twap job %s", algo_id)
            self._archive = [a for a in self._archive if a.get("algo_id") != algo_id]
            self._archive.insert(0, snap)
            self._archive = self._archive[:HISTORY_CAP]
        self.publish()

    def on_gateway(self, msg: AlgoPayload) -> None:
        for job in list(self._jobs.values()):
            job.on_gateway(msg)

    async def restore(self) -> None:
        store.init_db()
        self._archive = store.load_history(HISTORY_CAP, algo_type=ALGO_ID)
        self._id_seq = 0
        self._coi_seq = 0
        for snap in self._archive:
            self._note_seqs(snap)
        rows = store.load_active_runs(algo_type=ALGO_ID)
        if not rows:
            logger.info("no active advanced-twap jobs to restore")
            self.publish()
            return
        restored: list[tuple[str, AdvancedTwapRunner]] = []
        for row in rows:
            algo_id = str(row.get("algo_id") or "")
            try:
                job = AdvancedTwapRunner(self)
                job.hydrate_from_row(row)
                self._jobs[algo_id] = job
                self._note_seqs(job.snapshot())
                for c in job.ledger.clips:
                    seq = c.client_order_index - self._coi_base
                    if seq > self._coi_seq:
                        self._coi_seq = seq
                restored.append((algo_id, job))
            except Exception:
                logger.exception("failed to restore twap job %s — archiving as stopped", algo_id)
                _ = self._jobs.pop(algo_id, None)
                self._archive_broken_row(row)
        for algo_id, job in restored:
            if algo_id not in self._jobs:
                continue
            try:
                await job.resume()
            except Exception:
                logger.exception("failed to resume twap job %s — archiving as stopped", algo_id)
                _ = self._jobs.pop(algo_id, None)
                row = next((r for r in rows if str(r.get("algo_id")) == algo_id), {})
                self._archive_broken_row(row)
        self.publish()

    def _note_seqs(self, snap: Mapping[str, object]) -> None:
        algo_id = str(snap.get("algo_id") or "")
        m = _TW_ID.match(algo_id)
        if m:
            n = int(m.group(1))
            if n > self._id_seq:
                self._id_seq = n

    def _archive_broken_row(self, row: Mapping[str, object]) -> None:
        algo_id = str(row.get("algo_id") or "")
        try:
            store.upsert_run(
                {
                    "algo_id": algo_id,
                    "algo_type": ALGO_ID,
                    "status": ChaseStatus.STOPPED.value,
                    "market_index": row.get("market_index") or 0,
                    "symbol": row.get("symbol") or "",
                    "reduce_only": row.get("reduce_only"),
                    "side": row.get("side"),
                    "qty": row.get("qty"),
                    "remaining": row.get("remaining"),
                    "filled": row.get("filled"),
                    "created_at": row.get("created_at") or 0,
                    "error": "restore failed",
                    "params_json": row.get("params_json") or {},
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
            logger.exception("failed to archive broken twap job %s", algo_id)

    async def drain_for_shutdown(self) -> None:
        for job in list(self._jobs.values()):
            try:
                await job.drain_for_shutdown()
            except Exception:
                logger.exception("twap drain failed for %s", job.algo_id)

    async def pause_for_market(self, market_index: int | None) -> None:
        for job in list(self._jobs.values()):
            if job.status != ChaseStatus.RUNNING:
                continue
            if market_index is not None and job.market_index != market_index:
                continue
            try:
                await job.pause()
            except Exception:
                logger.exception("twap pause_for_market failed for %s", job.algo_id)

    async def flush(self) -> None:
        for job in list(self._jobs.values()):
            if job.algo_id:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("twap flush persist failed for %s", job.algo_id)

    async def start(
        self,
        *,
        market_index: int,
        params: AdvancedTwapParams,
        reduce_only: bool = False,
    ) -> None:
        ex = self.execution()
        if ex.ensure_book:
            ok = await ex.ensure_book(market_index)
            if ok is False:
                raise ValueError("Order book not synced")
        algo_id = self.alloc_id()
        job = AdvancedTwapRunner(self)
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
