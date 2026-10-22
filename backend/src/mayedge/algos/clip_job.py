"""The shared half of a Clip algo's runner: start, resume, pause, stop and the loop.

Chase, Ladder and Grid each decide their quotes in ``_evaluate``. Everything around
it lives here: the wake events, the loop that calls ``_evaluate``, auto-resume after a
recoverable error, and pulling venue Clips on pause, stop and shutdown. A subclass
names its ``LABEL``, builds its state in ``start`` and ``hydrate_from_row``, and
calls ``_begin`` for the first evaluate.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Protocol

from mayedge.algos.chase.config import AUTO_RESUME_ERRORS
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.fills import FillState
from mayedge.algos.chase.iceberg import Action
from mayedge.algos.chase.place import ChasePlaceMixin
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus, ClipBookView
from mayedge.lighter.budget import BudgetRefused, budget
from mayedge.lighter.errors import is_blocked, is_invalid_nonce
from mayedge.rows import items

logger = logging.getLogger(__name__)

_BOOK_MSGS = frozenset({"order_book", "order_book_snapshot", "order_book_delta"})


class JobState(FillState, Protocol):
    algo_id: str
    symbol: str


class ClipJob[BookT: ClipBookView, StateT: JobState](ChasePlaceMixin[BookT, StateT]):
    """One Clip algo job. Its book owns many of these."""

    def __init__(self, book: BookT, state: StateT) -> None:
        self._book = book
        self._state = state
        self._cois: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._canceling = False
        self._last_tx_ms = 0
        self._backoff_until = 0
        self._backoff_reason: str | None = None
        self._pending_trades: list[dict[str, Any]] = []
        self._missing_refreshed: set[int] = set()
        self._unproven_retry_at = 0

    @property
    def state(self) -> StateT:
        return self._state

    def _restore_state(self, state: StateT) -> None:
        """Take a state read from a stored run: its clips are this job's, its timers start fresh."""
        self._state = state
        self._cois = {c.client_order_index for c in state.ledger.clips}
        self._reset_job()

    def _reset_job(self) -> None:
        """Forget the last run's timers and queues before a start or a restore."""
        self._stop.clear()
        self._wake.clear()
        self._last_tx_ms = 0
        self._backoff_until = 0
        self._backoff_reason = None
        self._canceling = False
        self._pending_trades.clear()
        self._missing_refreshed.clear()
        self._unproven_retry_at = 0

    def _exec(self) -> ChaseExecution:
        return self._book.execution()

    def _publish(self) -> None:
        self._book.publish()

    def _finish(self) -> None:
        self._book.finish(self)

    def _next_coi(self) -> int:
        coi = self._book.alloc_coi()
        self._cois.add(coi)
        return coi

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def _ensure_task_or_wake(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        else:
            self._wake.set()

    async def _halt_task(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _hold(self, reason: str) -> None:
        """Clips are off the venue: quote nothing, and say why."""
        self._state.quote_action = Action.PAUSE.value
        self._state.reason = reason
        self._state.rest_price = None
        self._state.rest_qty = None
        self._state.error = None

    async def _evaluate_or_error(self, step: str) -> bool:
        try:
            await self._evaluate()
        except Exception:
            logger.exception("%s %s evaluate failed for %s", self.LABEL, step, self._state.algo_id)
            self._state.status = ChaseStatus.ERROR
            self._state.error = f"{step} evaluate failed"
            self._publish()
            return False
        return True

    def _log_restored(self, how: str) -> None:
        logger.info(
            "%s %s job %s market=%s remaining=%s",
            how,
            self.LABEL,
            self._state.algo_id,
            self._state.symbol or self._state.market_index,
            self._state.remaining,
        )

    async def _begin(self) -> None:
        """First evaluate of a new job. A job that will not quote is stopped."""
        try:
            await self._evaluate()
        except Exception:
            await self.stop()
            raise
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())

    async def resume(self) -> None:
        """Continue a hydrated RUNNING/ERROR/PAUSED job after process restart."""
        if self._state.status not in ACTIVE_STATUSES:
            raise ValueError(f"cannot resume status={self._state.status}")
        if not self._state.symbol:
            meta = self._exec().get_market_by_index(self._state.market_index)
            if meta:
                self._state.symbol = meta.symbol

        if not await self._rearm_from_venue():
            self._ensure_task()
            self._publish()
            return

        if self._state.status == ChaseStatus.ERROR:
            if self._state.error in AUTO_RESUME_ERRORS:
                self._state.status = ChaseStatus.RUNNING
                self._state.reason = None
                self._state.error = None
                self._ensure_task()
                if not await self._evaluate_or_error("resume"):
                    return
                self._log_restored("auto-resumed")
                self._publish()
                return
            self._ensure_task()
            self._log_restored("restored error (awaiting unpause)")
            self._publish()
            return
        if self._state.status == ChaseStatus.PAUSED:
            self._ensure_task()
            self._log_restored("restored paused")
            self._publish()
            return
        if not await self._evaluate_or_error("resume"):
            return
        if self._state.status == ChaseStatus.RUNNING:
            self._task = asyncio.create_task(self._run())
            self._log_restored("restored")

    async def pause(self) -> None:
        """User pause: pull clips and hold the master until unpause."""
        if self._state.status != ChaseStatus.RUNNING:
            raise ValueError(f"cannot pause status={self._state.status}")
        if await self._cancel_algo_orders():
            self._state.status = ChaseStatus.PAUSED
            self._hold("user_paused")
        else:
            self._state.status = ChaseStatus.ERROR
            self._state.error = "pause: cancel incomplete"
        self._wake.set()
        self._publish()

    async def unpause(self) -> None:
        """User resume after pause or error — start quoting again."""
        if self._state.status not in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
            raise ValueError(f"cannot unpause status={self._state.status}")
        if not await self._rearm_from_venue():
            self._ensure_task_or_wake()
            self._publish()
            return
        self._state.status = ChaseStatus.RUNNING
        self._state.reason = None
        self._state.error = None
        self._ensure_task_or_wake()
        if await self._evaluate_or_error("unpause"):
            self._publish()

    def on_gateway(self, msg: dict[str, Any]) -> None:
        if self._state.status not in ACTIVE_STATUSES:
            return
        kind = msg.get("type")
        if kind == "account_trades":
            trades = items(msg.get("trades"))
            if trades:
                self._pending_trades.extend(trades)
                self._wake.set()
            return
        if self._state.status != ChaseStatus.RUNNING:
            return
        book = kind in _BOOK_MSGS and msg.get("market_index") == self._state.market_index
        if book or kind == "account":
            self._wake.set()

    async def drain_for_shutdown(self) -> None:
        """Pull venue clips before process exit; parent state persists for restore."""
        if self._state.status not in ACTIVE_STATUSES:
            return
        await self._halt_task()
        if self._state.status not in (ChaseStatus.RUNNING, ChaseStatus.ERROR):
            return
        complete = await self._cancel_algo_orders()
        if self._state.status == ChaseStatus.RUNNING:
            if complete:
                self._hold("shutdown")
            else:
                self._state.status = ChaseStatus.ERROR
                self._state.error = "shutdown: cancel incomplete"
        self._publish()

    async def stop(self) -> None:
        await self._halt_task()
        complete = await self._cancel_algo_orders()
        if self._state.status in ACTIVE_STATUSES:
            if complete:
                self._state.status = ChaseStatus.STOPPED
                self._finish()
            else:
                self._state.status = ChaseStatus.ERROR
                self._state.error = self._state.error or "stop: cancel incomplete"
                self._publish()

    async def _run(self) -> None:
        token = budget.enter_lane("algo")
        try:
            while not self._stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                self._wake.clear()
                if self._stop.is_set():
                    break
                if (
                    self._state.status == ChaseStatus.ERROR
                    and self._state.error in AUTO_RESUME_ERRORS
                ):
                    try:
                        await self.unpause()
                    except Exception:
                        logger.exception(
                            "%s auto-resume failed for %s", self.LABEL, self._state.algo_id
                        )
                    continue
                if self._state.status in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
                    continue
                try:
                    await self._evaluate()
                except Exception as e:
                    if isinstance(e, BudgetRefused) or is_blocked(e) or is_invalid_nonce(e):
                        self._handle_tx_err(e)
                        continue
                    logger.exception("%s error", self.LABEL)
                    self._state.status = ChaseStatus.ERROR
                    self._state.error = str(e)
                    await self._cancel_algo_orders()
                    self._publish()
                    return
                if self._state.status in (ChaseStatus.PAUSED, ChaseStatus.ERROR):
                    continue
                if self._state.status != ChaseStatus.RUNNING:
                    break
        finally:
            budget.leave_lane(token)
