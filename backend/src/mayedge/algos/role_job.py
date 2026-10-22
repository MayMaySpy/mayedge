"""The shared half of a Trail or Planner runner: Clips by role, evidence and the loop.

Both keep a few Clips, each with a role ("stop", "fire", "entry", "tp1", ...), and
believe a fill only from the account feed. The rules that differ are hooks:
which side a role sends on, which Clips the trade tape credits, which open orders
carry a fill, and whether the job follows prices at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from mayedge.algos import common
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus
from mayedge.algos.ledger import Clip, ClipSide, Ledger
from mayedge.algos.planner import venue
from mayedge.lighter.budget import BudgetRefused, budget
from mayedge.lighter.errors import is_blocked, is_invalid_nonce, is_order_not_found
from mayedge.rows import is_obj, items

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


class RoleBook(Protocol):
    def publish(self) -> None: ...

    def finish(self, job: Any) -> None: ...

    def alloc_coi(self) -> int: ...

    def execution(self) -> ChaseExecution: ...


class RoleState(Protocol):
    status: ChaseStatus
    params: Any
    market_index: int
    algo_id: str
    reason: str | None
    error: str | None
    ledger: Ledger
    roles: dict[int, str]


class RoleJob[BookT: RoleBook, StateT: RoleState]:
    LABEL: ClassVar[str]  # how logs name the algo
    # A cancel waits this many tries, this long apart, for the feed to show the order.
    CANCEL_WAIT_TRIES: ClassVar[int]
    CANCEL_WAIT_S: ClassVar[float]
    # An order the account feed has not shown after this was refused.
    ACK_GRACE_MS: ClassVar[int]
    # A Clip gone from the book is believed after this.
    MISSING_GRACE_MS: ClassVar[int]
    RATE_LIMIT_COOLDOWN_MS: ClassVar[int]

    def __init__(self, book: BookT, state: StateT) -> None:
        self._book = book
        self._state = state
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._pending_trades: list[dict[str, Any]] = []
        # Trail F9: every print since the last evaluate, oldest first.
        self._prints: list[Decimal] = []
        self._backoff_until = 0
        self._flat_since: int | None = None

    @property
    def state(self) -> StateT:
        return self._state

    # ── what a subclass supplies ─────────────────────────────────────────

    async def _evaluate(self) -> None:
        raise NotImplementedError

    def _clip_side(self, role: str) -> ClipSide:
        raise NotImplementedError

    def _follows_prices(self) -> bool:
        """True when a part of the job trails a price, so prints and stats wake it."""
        return self._state.params is not None

    def _trade_counts(self, clip: Clip) -> bool:
        """True when the trade tape is evidence for this Clip's fills."""
        del clip
        return True

    def _book_fills(self, clip: Clip) -> bool:
        """True when the open order's remaining size is evidence for this Clip's fills."""
        del clip
        return False

    def _absence_counts(self, clip: Clip) -> bool:
        """True when this Clip missing from the book starts its gone clock."""
        del clip
        return True

    # ── reads ────────────────────────────────────────────────────────────

    def _exec(self) -> ChaseExecution:
        return self._book.execution()

    def _publish(self) -> None:
        self._book.publish()

    def _tick(self) -> Decimal:
        meta = self._exec().get_market_by_index(self._state.market_index)
        if not meta:
            return ZERO
        return Decimal(10) ** -meta.price_decimals

    def _qty_step(self) -> Decimal:
        meta = self._exec().get_market_by_index(self._state.market_index)
        if not meta:
            return ZERO
        return Decimal(10) ** -meta.size_decimals

    def _mark(self) -> Decimal:
        meta = self._exec().get_market_by_index(self._state.market_index)
        if not meta:
            return ZERO
        return venue.dec(meta.mark_price) or venue.dec(meta.last_trade_price) or ZERO

    def _prices(self) -> list[Decimal]:
        """The Reference's prices since the last look (Trail F9). Mark is read as it is now."""
        if not self._follows_prices():
            return []
        if self._state.params.reference == "last":
            prints, self._prints = self._prints, []
            return prints
        mark = self._mark()
        return [mark] if mark > 0 else []

    # ── clips ────────────────────────────────────────────────────────────

    def _role(self, clip: Clip) -> str:
        return self._state.roles.get(clip.seq, "")

    def _latest(self, role: str) -> Clip | None:
        for c in reversed(self._state.ledger.clips):
            if self._role(c) == role:
                return c
        return None

    def _live(self, role: str) -> Clip | None:
        c = self._latest(role)
        return c if c is not None and c.status == "live" else None

    def _place(self, role: str, *, price: Decimal, qty: Decimal) -> Clip:
        st = self._state
        clip = st.ledger.place(
            client_order_index=self._book.alloc_coi(),
            price=price,
            qty=qty,
            now=common.now_ms(),
            side=self._clip_side(role),
        )
        st.roles[clip.seq] = role
        return clip

    async def _await_order_index(self, clip: Clip) -> None:
        """The venue's order_index, which a cancel or an Amend needs, once the feed shows it."""
        for _ in range(self.CANCEL_WAIT_TRIES):
            if clip.order_index or clip.status != "live":
                return
            self._sync_open(common.now_ms())
            if clip.order_index or clip.status != "live":
                return
            self._exec().kick_refresh()
            await asyncio.sleep(self.CANCEL_WAIT_S)

    async def _cancel_clip(self, clip: Clip) -> bool:
        """True once the venue has the cancel, or the order is already gone."""
        if clip.status != "live":
            return True
        await self._await_order_index(clip)
        if clip.status != "live":
            return True
        if not clip.order_index:
            return False
        try:
            await self._exec().cancel_order(self._state.market_index, clip.order_index)
        except Exception as e:
            if not is_order_not_found(e):
                raise
        clip.status = "cancelled"
        clip.closed_at = common.now_ms()
        return True

    async def _cancel_all(self) -> bool:
        complete = True
        for clip in list(self._state.ledger.live_clips()):
            try:
                complete = await self._cancel_clip(clip) and complete
            except Exception:
                logger.exception("%s cancel failed for %s", self.LABEL, self._state.algo_id)
                complete = False
        return complete

    async def _pull_tickets(self, orders: list[dict[str, Any]]) -> int:
        """Cancel the Tickets this job replaces. Returns how many are still live."""
        left = 0
        for o in orders:
            try:
                await self._exec().cancel_order(
                    int(o.get("market_index") or 0), int(o.get("order_index") or 0)
                )
            except Exception as e:
                if not is_order_not_found(e):
                    logger.warning("%s: replaced order %s not cancelled: %s", self.LABEL, o, e)
                    left += 1
        return left

    # ── evidence ─────────────────────────────────────────────────────────

    def _sync_open(self, now: int) -> None:
        st = self._state
        cois = {c.client_order_index: c for c in st.ledger.live_clips()}
        rows: dict[int, dict[str, Any]] = {}
        for o in venue.open_orders(self._exec()):
            try:
                coi = int(o.get("client_order_index") or 0)
            except (TypeError, ValueError):
                continue
            if coi in cois:
                rows[coi] = o
        for coi, clip in cois.items():
            row = rows.get(coi)
            if row is not None:
                oid = int(row.get("order_index") or 0) or None
                if self._book_fills(clip):
                    st.ledger.apply_open(
                        clip,
                        venue.dec(row.get("remaining")) or ZERO,
                        now=now,
                        order_index=oid,
                        book_filled=venue.dec(row.get("filled")),
                    )
                    continue
                clip.seen_on_book = True
                clip.missing_since = None
                if oid:
                    clip.order_index = oid
                continue
            if not self._absence_counts(clip):
                continue
            if clip.missing_since is None:
                clip.missing_since = now

    def _gone(self, clip: Clip, now: int) -> bool:
        """Off the book long enough to believe, and not merely unacknowledged."""
        if clip.missing_since is None or now - clip.missing_since < self.MISSING_GRACE_MS:
            return False
        return clip.seen_on_book or now - clip.placed_at >= self.ACK_GRACE_MS

    def _drain_trades(self, now: int) -> None:
        trades, self._pending_trades = self._pending_trades, []
        st = self._state
        for t in trades:
            if int(t.get("market_index") or 0) not in (0, st.market_index):
                continue
            qty = venue.dec(t.get("size")) or ZERO
            if qty <= 0:
                continue
            for key, oid_key in (("bid_client_id", "bid_id"), ("ask_client_id", "ask_id")):
                coi = int(t.get(key) or 0)
                if not coi:
                    continue
                clip = st.ledger.find_clip(client_order_index=coi)
                if clip is None or not self._trade_counts(clip):
                    continue
                st.ledger.apply_trade(
                    clip,
                    qty,
                    now=now,
                    price=venue.dec(t.get("price")),
                    trade_id=int(t.get("trade_id") or 0) or None,
                    order_index=int(t.get(oid_key) or 0) or None,
                )

    # ── loop ─────────────────────────────────────────────────────────────

    def on_gateway(self, msg: dict[str, Any]) -> None:
        st = self._state
        if st.status not in ACTIVE_STATUSES:
            return
        kind = msg.get("type")
        if kind == "account_trades":
            trades = items(msg.get("trades"))
            if trades:
                self._pending_trades.extend(t for t in trades if is_obj(t))
                self._wake.set()
            return
        if kind == "account":
            self._wake.set()
            return
        if not self._follows_prices():
            return
        if kind == "prints":
            if st.params.reference != "last" or venue.market_of(msg) != st.market_index:
                return
            for raw in msg.get("prices") or ():
                px = venue.dec(raw)
                if px and px > 0:
                    self._prints.append(px)
            self._wake.set()
            return
        if kind == "market_stats":
            for m in msg.get("markets") or ():
                if is_obj(m) and venue.market_of(m) == st.market_index:
                    self._wake.set()
                    return

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def resume(self) -> None:
        """Carry on after a restart: catch up from the feed, then run."""
        if self._state.status not in ACTIVE_STATUSES:
            return
        await self._evaluate()
        self._publish()
        if self._state.status in ACTIVE_STATUSES:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        token = budget.enter_lane("algo")
        try:
            while not self._stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                self._wake.clear()
                if self._stop.is_set():
                    break
                if common.now_ms() < self._backoff_until:
                    continue
                try:
                    await self._evaluate()
                except Exception as e:
                    if isinstance(e, BudgetRefused) or is_blocked(e) or is_invalid_nonce(e):
                        self._backoff_until = common.now_ms() + self.RATE_LIMIT_COOLDOWN_MS
                        continue
                    # The venue stop stays where it is. The job stops acting, not protecting.
                    logger.exception("%s error on %s", self.LABEL, self._state.algo_id)
                    self._state.status = ChaseStatus.ERROR
                    self._state.error = str(e) or type(e).__name__
                    self._publish()
                if self._state.status not in ACTIVE_STATUSES:
                    break
        finally:
            budget.leave_lane(token)

    # ── operator ─────────────────────────────────────────────────────────

    async def pause(self) -> None:
        if self._state.status == ChaseStatus.RUNNING:
            self._state.status = ChaseStatus.PAUSED
            self._state.reason = "paused"
            self._publish()

    def _running_again(self) -> None:
        self._publish()
        self._wake.set()
        self._ensure_task()

    async def _halt(self) -> None:
        self._stop.set()
        self._wake.set()
        task, self._task = self._task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _end_stop(self, complete: bool, reason: str = "stopped") -> None:
        st = self._state
        if complete:
            st.status = ChaseStatus.STOPPED
            st.reason = reason
            self._book.finish(self)
        else:
            st.status = ChaseStatus.ERROR
            st.error = "stop: cancel incomplete"
            self._publish()
