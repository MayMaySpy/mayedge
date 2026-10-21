"""The shared half of a Clip algo's book: ids, persistence, history, restore and stop.

Chase, Grid, Ladder and TWAP keep many jobs whose Clips live in one Ledger each. A
subclass names its algo, its id prefix and its client_order_index band, makes a
runner, and adds its own start checks. Planner and Trail own more than Clips and keep
their own books. ``AlgoBook`` is the shared base in this file. ``ClipBook`` adds the
clip-only methods. This is the method-by-method diff the split follows.

| Method | Kind | What differs |
| --- | --- | --- |
| ``_new_runner`` | hook | each book builds its own runner |
| ``_restore_needs_books`` | hook | clip waits for ``is_book_synced`` and calls ``ensure_book``; TWAP, trail and planner do not |
| ``_on_restored``, ``_on_finished`` | hook | trail and planner call ``_sync_watch``; clip does nothing |
| ``_save_counters``, ``alloc_id``, ``alloc_coi`` | shared | id prefix and the exhausted-range label |
| ``execution``, ``has``, ``algo_type``, ``on_gateway``, ``pause``, ``unpause``, ``flush``, ``drain_for_shutdown`` | shared | |
| ``publish``, ``finish``, ``to_dict`` | shared | persist writes the same ledger fields |
| ``_wait_feeds_ready`` | shared | the book-sync wait is the hook above; trail and planner wait for the account feed and hydrated orders |
| ``restore`` | shared | clip seeds counters from its id prefix and COI band; trail and planner read their own keys. Clip archives a job that will not resume. Trail and planner leave it up, status error, and call ``_sync_watch``. Trail skips the feed wait when nothing restored; planner still waits. Clip logs and returns when no row is active; planner returns without that log |
| ``_archive_broken`` | shared | clip keeps the ledger and remembers history. Trail and planner write a short stopped row; planner also keeps ``filled`` |
| ``pause_for_market`` | shared | clip pauses running jobs; trail and planner stop every job on the market |
| ``stop`` | shared | clip publishes when the id is missing; planner does not. Trail adds ``keep_stop`` |
| ``_ensure_book``, ``_launch``, ``live_on_market_side``, ``missing_fill_grace_ms`` | clip | |
| ``set_market_conflict``, ``set_watch_prints``, ``take_amend`` | trail and planner | the same minute budget |
| ``_sync_watch``, ``_check_free`` | one book | the "want prints" test and the free-market rule differ |
| ``preview_from_body``, ``start_from_body`` | one book | both books, different bodies |
| ``edit_from_body``, ``stop_live_on_market`` | trail | |
| ``replan_from_body``, ``finish_entry`` | planner | |
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, ClassVar, Protocol, cast

from mayedge import db as store
from mayedge import feed_health
from mayedge.algos.chase.config import HISTORY_CAP, RESTORE_FEED_TIMEOUT_S
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.ledger import Ledger
from mayedge.algos.trail.config import MARKET_AMENDS_PER_MIN
from mayedge.rows import is_list, is_obj

logger = logging.getLogger(__name__)

AlgoPayload = dict[str, object]

# Keys of a stored run that are its Ledger, not its row.
_LEDGER_KEYS = frozenset(
    {"next_clip", "next_fill", "trade_ids", "trade_qty_by_clip", "clips", "fills"}
)


class JobView(Protocol):
    """What the book reads off a job: a runner's state, or a runner that is its own state."""

    @property
    def algo_id(self) -> str: ...

    @property
    def market_index(self) -> int: ...

    @property
    def status(self) -> ChaseStatus: ...

    @property
    def ledger(self) -> Ledger: ...


class ClipRunner(Protocol):
    def snapshot(self) -> dict[str, Any]: ...

    def hydrate_from_row(self, row: dict[str, Any]) -> None: ...

    def on_gateway(self, msg: dict[str, Any]) -> None: ...

    async def resume(self) -> None: ...

    async def pause(self) -> None: ...

    async def unpause(self) -> None: ...

    async def stop(self) -> None: ...

    async def drain_for_shutdown(self) -> None: ...


def as_int(raw: object, default: int = 0) -> int:
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
    return {int(str(x)) for x in cast("Iterable[object]", raw)}


def _as_int_str_map(raw: object) -> dict[int, str]:
    if not is_obj(raw):
        return {}
    items = cast(dict[object, object], raw)
    return {int(str(k)): str(v) for k, v in items.items()}


def _as_record_list(raw: object) -> list[AlgoPayload]:
    if not is_list(raw):
        return []
    return [cast(AlgoPayload, item) for item in cast("list[object]", raw) if is_obj(item)]


def _created_at(snap: Mapping[str, object]) -> int:
    return as_int(snap.get("created_at"))


class MarketWatch:
    """Amend budget and print watch. Trail and planner use it. Clip books do not."""

    def __init__(
        self,
        market_conflict: Callable[[int], bool] | None = None,
        watch_prints: Callable[[int, bool], None] | None = None,
    ) -> None:
        self._market_conflict = market_conflict
        self._watch_prints = watch_prints
        self._amends: dict[int, deque[int]] = {}

    def set_market_conflict(self, fn: Callable[[int], bool]) -> None:
        self._market_conflict = fn

    def set_watch_prints(self, fn: Callable[[int, bool], None]) -> None:
        self._watch_prints = fn

    def take_amend(self, market_index: int, now_ms: int) -> bool:
        """One amend budget a minute, shared by the jobs on a market."""
        sent = self._amends.setdefault(market_index, deque())
        while sent and now_ms - sent[0] >= 60_000:
            sent.popleft()
        if len(sent) >= MARKET_AMENDS_PER_MIN:
            return False
        sent.append(now_ms)
        return True


class AlgoBook[R: ClipRunner]:
    """Counters, persistence, restore and stop. A subclass supplies the runner."""

    ALGO_ID: ClassVar[str]
    ID_PREFIX: ClassVar[str]
    LABEL: ClassVar[str]  # how logs and refusals name the algo
    COI_BASE: ClassVar[int]
    COI_END: ClassVar[int]
    # A restore waits for the account feed and the jobs' books before resuming them.
    RESTORE_WAITS_FOR_FEEDS: ClassVar[bool] = True

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
        self._coi_base = coi_base if coi_base is not None else self.COI_BASE
        self._coi_end = coi_end if coi_end is not None else self.COI_END
        self._jobs: dict[str, R] = {}
        self._archive: list[AlgoPayload] = []
        self._id_seq = 0
        self._coi_seq = 0

    # ── what a subclass supplies ─────────────────────────────────────────

    def _new_runner(self) -> R:
        raise NotImplementedError

    def _view(self, job: R) -> JobView:
        raise NotImplementedError

    def _restore_needs_books(self) -> bool:
        return self.RESTORE_WAITS_FOR_FEEDS

    def _restore_waits_for_account(self) -> bool:
        """Trail and planner wait for the account feed. A clip book waits only when it also waits for books."""
        return self._restore_needs_books()

    def _seeds_counters(self) -> bool:
        """Clip books seed from their id prefix and client-order band. Trail and planner do not."""
        return True

    def _log_empty_restore(self) -> bool:
        return True

    def _wait_with_nothing_restored(self) -> bool:
        """Planner still waits for the account feed when every row failed to hydrate."""
        return False

    def _cancel_all_stops(self) -> bool:
        """Trail and planner stop jobs on cancel-all. Clip books pause the running ones."""
        return False

    def _remember_broken(self) -> bool:
        return True

    def _on_restored(self, job: R) -> None:
        del job

    def _on_finished(self, job: R) -> None:
        del job

    def _resume_failed(self, job: R, row: Mapping[str, object]) -> None:
        algo_id = str(row.get("algo_id") or "") or self._view(job).algo_id
        logger.exception("failed to resume %s job %s — archiving as stopped", self.LABEL, algo_id)
        _ = self._jobs.pop(algo_id, None)
        self._archive_broken(row)

    def _broken_run(self, row: Mapping[str, object]) -> dict[str, Any]:
        algo_id = str(row.get("algo_id") or "")
        run: dict[str, Any] = {k: v for k, v in row.items() if k not in _LEDGER_KEYS}
        run.update(
            algo_id=algo_id,
            algo_type=self.ALGO_ID,
            status=ChaseStatus.STOPPED.value,
            market_index=row.get("market_index") or 0,
            symbol=row.get("symbol") or "",
            created_at=row.get("created_at") or 0,
            error="restore failed",
        )
        return run

    # ── reads ────────────────────────────────────────────────────────────

    @property
    def algo_type(self) -> str:
        return self.ALGO_ID

    def execution(self) -> ChaseExecution:
        return self._execution_fn()

    def has(self, algo_id: str) -> bool:
        return algo_id in self._jobs

    def _live(self, market_index: int, exclude: str | None) -> Iterable[R]:
        for job in self._jobs.values():
            view = self._view(job)
            if exclude and view.algo_id == exclude:
                continue
            if view.market_index == market_index and view.status in ACTIVE_STATUSES:
                yield job

    def live_on_market(self, market_index: int, *, exclude: str | None = None) -> bool:
        return any(True for _ in self._live(market_index, exclude))

    def to_dict(self) -> AlgoPayload:
        working = [
            job.snapshot()
            for job in self._jobs.values()
            if self._view(job).status in ACTIVE_STATUSES
        ]
        working.sort(key=_created_at, reverse=True)
        return {
            "type": "algo",
            "id": self.ALGO_ID,
            "working": working,
            "history": list(self._archive),
        }

    # ── ids ──────────────────────────────────────────────────────────────

    def _save_counters(self) -> None:
        store.save_book_counters(self.ALGO_ID, self._id_seq, self._coi_seq)

    def alloc_id(self) -> str:
        self._id_seq += 1
        self._save_counters()
        return f"{self.ID_PREFIX}{self._id_seq:04d}"

    def alloc_coi(self) -> int:
        self._coi_seq += 1
        coi = self._coi_base + self._coi_seq
        if coi >= self._coi_end:
            raise RuntimeError(f"{self.LABEL} client_order_index range exhausted")
        self._save_counters()
        return coi

    # ── persistence ──────────────────────────────────────────────────────

    def _persist_job(self, job: R, *, archived: bool) -> None:
        ledger = self._view(job).ledger.to_persist()
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

    def _remember(self, snap: AlgoPayload) -> None:
        algo_id = snap.get("algo_id")
        self._archive = [a for a in self._archive if a.get("algo_id") != algo_id]
        self._archive.insert(0, snap)
        self._archive = self._archive[:HISTORY_CAP]

    def publish(self) -> None:
        for job in self._jobs.values():
            view = self._view(job)
            if view.algo_id and view.status in ACTIVE_STATUSES:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("failed to persist %s job %s", self.LABEL, view.algo_id)
        self._broadcast_fn(self.to_dict())

    def finish(self, job: R) -> None:
        snap = job.snapshot()
        algo_id = self._view(job).algo_id
        _ = self._jobs.pop(algo_id, None)
        if algo_id:
            try:
                self._persist_job(job, archived=True)
            except Exception:
                logger.exception("failed to archive %s job %s", self.LABEL, algo_id)
            self._remember(snap)
        self._on_finished(job)
        self.publish()

    def on_gateway(self, msg: AlgoPayload) -> None:
        for job in list(self._jobs.values()):
            job.on_gateway(msg)

    async def flush(self) -> None:
        """Final write of all live jobs (e.g. before shutdown cancel)."""
        for job in list(self._jobs.values()):
            algo_id = self._view(job).algo_id
            if algo_id:
                try:
                    self._persist_job(job, archived=False)
                except Exception:
                    logger.exception("%s flush persist failed for %s", self.LABEL, algo_id)
        self._save_counters()

    # ── restore ──────────────────────────────────────────────────────────

    async def _wait_feeds_ready(self, market_indices: set[int]) -> None:
        if not self._restore_waits_for_account():
            return
        if self._restore_needs_books() and not market_indices:
            return
        deadline = time.monotonic() + RESTORE_FEED_TIMEOUT_S
        while time.monotonic() < deadline:
            ex = self.execution()
            ready = feed_health.snapshot().get("account_ws") == "live" and ex.orders_hydrated()
            if ready and self._restore_needs_books():
                ready = all(ex.is_book_synced(mi) for mi in market_indices)
            if ready:
                return
            await asyncio.sleep(0.1)
        if self._restore_needs_books():
            logger.warning(
                "restore: feeds not ready within %.0fs for markets %s",
                RESTORE_FEED_TIMEOUT_S,
                sorted(market_indices),
            )
            return
        logger.warning(
            "%s restore: account feed not ready within %.0fs",
            self.LABEL.lower(),
            RESTORE_FEED_TIMEOUT_S,
        )

    async def restore(self) -> None:
        """Load counters and history, then resume every active job from SQLite."""
        store.init_db()
        if self._seeds_counters():
            counters = store.load_book_counters(
                self.ALGO_ID, id_prefix=self.ID_PREFIX, coi_band=(self._coi_base, self._coi_end)
            )
        else:
            counters = store.load_book_counters(self.ALGO_ID)
        self._id_seq = counters["id_seq"]
        self._coi_seq = counters["coi_seq"]
        self._archive = store.load_history(HISTORY_CAP, algo_type=self.ALGO_ID)

        rows = store.load_active_runs(algo_type=self.ALGO_ID)
        if not rows:
            if self._log_empty_restore():
                logger.info("no active %s jobs to restore", self.LABEL)
            self.publish()
            return

        market_indices: set[int] = set()
        restored: list[tuple[str, R, Mapping[str, object]]] = []
        for row in rows:
            algo_id = str(row.get("algo_id") or "")
            try:
                job = self._new_runner()
                job.hydrate_from_row(row)
                self._jobs[algo_id] = job
                mi = int(row.get("market_index") or 0)
                if mi and self._restore_needs_books():
                    market_indices.add(mi)
                    ex = self.execution()
                    if ex.ensure_book:
                        await ex.ensure_book(mi)
                restored.append((algo_id, job, row))
            except Exception:
                logger.exception(
                    "failed to restore %s job %s — archiving as stopped", self.LABEL, algo_id
                )
                _ = self._jobs.pop(algo_id, None)
                self._archive_broken(row)

        if restored or self._wait_with_nothing_restored():
            await self._wait_feeds_ready(market_indices)

        for algo_id, job, row in restored:
            if algo_id not in self._jobs:
                continue
            self._on_restored(job)
            try:
                await job.resume()
            except Exception:
                self._resume_failed(job, row)
        self.publish()

    def _archive_broken(self, row: Mapping[str, object]) -> None:
        """Keep a job that would not come back as stopped history, with its ledger."""
        algo_id = str(row.get("algo_id") or "")
        try:
            run = self._broken_run(row)
            store.upsert_run(
                run,
                next_clip=as_int(row.get("next_clip"), 1),
                next_fill=as_int(row.get("next_fill"), 1),
                trade_ids=_as_int_set(row.get("trade_ids")),
                trade_qty_by_clip=_as_int_str_map(row.get("trade_qty_by_clip")),
                clips=_as_record_list(row.get("clips")),
                fills=_as_record_list(row.get("fills")),
                archived=True,
            )
            if self._remember_broken():
                snap = store.load_history(1, algo_type=self.ALGO_ID)
                if snap and snap[0].get("algo_id") == algo_id:
                    self._remember(snap[0])
        except Exception:
            logger.exception("failed to archive broken %s job %s", self.LABEL, algo_id)

    # ── control ──────────────────────────────────────────────────────────

    async def drain_for_shutdown(self) -> None:
        """Pull all venue Clips before process exit."""
        for job in list(self._jobs.values()):
            try:
                await job.drain_for_shutdown()
            except Exception:
                logger.exception("%s drain failed for %s", self.LABEL, self._view(job).algo_id)

    async def pause_for_market(self, market_index: int | None) -> None:
        """Pause running jobs on a market (or all) before a venue cancel-all."""
        for job in list(self._jobs.values()):
            view = self._view(job)
            if market_index is not None and view.market_index != market_index:
                continue
            if not self._cancel_all_stops() and view.status != ChaseStatus.RUNNING:
                continue
            try:
                if self._cancel_all_stops():
                    await job.stop()
                else:
                    await job.pause()
            except Exception:
                logger.exception("%s pause_for_market failed for %s", self.LABEL, view.algo_id)

    async def stop(self, algo_id: str | None = None) -> None:
        if algo_id:
            job = self._jobs.get(algo_id)
            if job:
                await job.stop()
            else:
                self.publish()
            return
        failed: Exception | None = None
        for job in list(self._jobs.values()):
            try:
                await job.stop()
            except Exception as e:
                logger.exception("stop failed for %s", self._view(job).algo_id)
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


class ClipBook[R: ClipRunner](AlgoBook[R]):
    """A clip algo's book: one ledger of clips, plus the order book at start."""

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int | None = None,
        coi_end: int | None = None,
        missing_fill_grace_ms: int = 800,
    ) -> None:
        super().__init__(
            execution=execution, broadcast=broadcast, coi_base=coi_base, coi_end=coi_end
        )
        self._missing_fill_grace_ms = missing_fill_grace_ms

    @property
    def missing_fill_grace_ms(self) -> int:
        return self._missing_fill_grace_ms

    def _side(self, job: R) -> str | None:
        """The side a job works, for books that allow one job per side."""
        del job
        return None

    def live_on_market_side(
        self, market_index: int, side: str, *, exclude: str | None = None
    ) -> bool:
        return any(self._side(job) == side for job in self._live(market_index, exclude))

    async def _ensure_book(self, market_index: int) -> None:
        ex = self.execution()
        if ex.ensure_book:
            ok = await ex.ensure_book(market_index)
            if ok is False:
                raise ValueError("Order book not synced")

    async def _launch(self, begin: Callable[[R, str], Awaitable[None]]) -> None:
        """Give a new job an id and start it; a job that will not start is forgotten."""
        algo_id = self.alloc_id()
        job = self._new_runner()
        self._jobs[algo_id] = job
        try:
            await begin(job, algo_id)
        except Exception:
            _ = self._jobs.pop(algo_id, None)
            raise
        self.publish()
