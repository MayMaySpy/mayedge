from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from mayedge.lighter.channels import message_market_index
from mayedge.lighter.models import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger(__name__)

BOOK_DEPTH = 40
BOOK_BROADCAST_MS = 0.08
BOOK_RESYNC_S = 30.0


class OrderBookFeed:
    """Local order book merge, nonce check, and outbound snapshot/delta coalescing."""

    def __init__(
        self,
        broadcast: Callable[[dict[str, Any]], None],
        *,
        resubscribe: Callable[[int], None] | None = None,
    ) -> None:
        self._broadcast = broadcast
        self._resubscribe = resubscribe
        self._order_books: dict[int, OrderBookSnapshot] = {}
        self._last_book_nonce: dict[int, int] = {}
        self._book_seq: dict[int, int] = {}
        self._book_synced: dict[int, bool] = {}
        self._pending_snapshot: set[int] = set()
        self._pending_delta_bids: dict[int, dict[str, str]] = {}
        self._pending_delta_asks: dict[int, dict[str, str]] = {}
        self._book_flush_task: asyncio.Task[None] | None = None
        self._resync_task: asyncio.Task[None] | None = None
        self._current_market_index: int | None = None
        self._pinned: set[int] = set()

    def set_current_market(self, market_index: int | None) -> None:
        self._current_market_index = market_index

    def pin(self, market_index: int) -> None:
        self._pinned.add(market_index)

    def unpin(self, market_index: int) -> None:
        self._pinned.discard(market_index)
        if market_index != self._current_market_index:
            self._book_synced[market_index] = False

    def _watched(self, market_index: int | None) -> bool:
        if market_index is None:
            return False
        return market_index == self._current_market_index or market_index in self._pinned

    def clear_pending(self) -> None:
        self._pending_snapshot.clear()
        self._pending_delta_bids.clear()
        self._pending_delta_asks.clear()

    def start_resync_loop(self, get_current: Callable[[], int | None]) -> None:
        if self._resync_task and not self._resync_task.done():
            return
        self._resync_task = asyncio.create_task(self._book_resync_loop(get_current))

    async def stop_resync_loop(self) -> None:
        if self._resync_task:
            self._resync_task.cancel()
            try:
                await self._resync_task
            except asyncio.CancelledError:
                pass
            self._resync_task = None

    @staticmethod
    def parse_levels(raw: list[Any] | None) -> list[OrderBookLevel]:
        levels: list[OrderBookLevel] = []
        for level in raw or []:
            if isinstance(level, dict):
                price = str(level.get("price", ""))
                size = str(level.get("size", ""))
            else:
                price = str(getattr(level, "price", ""))
                size = str(getattr(level, "size", ""))
            if price:
                levels.append(OrderBookLevel(price=price, size=size))
        return levels

    @staticmethod
    def _level_price(level: OrderBookLevel) -> float:
        try:
            return float(level.price)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def sorted_side(
        cls, levels: list[OrderBookLevel], *, bids: bool, depth: int = BOOK_DEPTH
    ) -> list[OrderBookLevel]:
        kept: list[OrderBookLevel] = []
        for lvl in levels:
            try:
                size = float(lvl.size)
            except (TypeError, ValueError):
                size = 0.0
            if size > 0 and lvl.price:
                kept.append(lvl)
        kept.sort(key=cls._level_price, reverse=bids)
        return kept[:depth]

    @classmethod
    def merge_side(
        cls,
        existing: list[OrderBookLevel],
        updates: list[OrderBookLevel],
        *,
        bids: bool,
        depth: int = BOOK_DEPTH,
    ) -> list[OrderBookLevel]:
        by_price = {lvl.price: lvl for lvl in existing}
        for lvl in updates:
            try:
                size = float(lvl.size)
            except (TypeError, ValueError):
                size = 0.0
            if size <= 0:
                by_price.pop(lvl.price, None)
            else:
                by_price[lvl.price] = lvl
        return cls.sorted_side(list(by_price.values()), bids=bids, depth=depth)

    def _next_book_seq(self, market_index: int) -> tuple[int, int]:
        prev = self._book_seq.get(market_index, 0)
        nxt = prev + 1
        self._book_seq[market_index] = nxt
        return prev, nxt

    def order_book_payload(
        self, market_index: int, *, bump_seq: bool = False
    ) -> dict[str, Any] | None:
        snap = self._order_books.get(market_index)
        if not snap:
            return None
        if bump_seq:
            _, seq = self._next_book_seq(market_index)
        else:
            seq = self._book_seq.get(market_index, 0)
        return {
            "type": "order_book_snapshot",
            "market_index": market_index,
            "seq": seq,
            "bids": [{"price": b.price, "size": b.size} for b in snap.bids],
            "asks": [{"price": a.price, "size": a.size} for a in snap.asks],
            "timestamp": snap.timestamp,
        }

    def best_bid_ask(self, market_index: int) -> tuple[str | None, str | None]:
        snap = self._order_books.get(market_index)
        if not snap:
            return None, None
        bid = snap.bids[0].price if snap.bids else None
        ask = snap.asks[0].price if snap.asks else None
        return bid, ask

    def has_book(self, market_index: int) -> bool:
        return market_index in self._order_books

    def is_synced(self, market_index: int) -> bool:
        return self._book_synced.get(market_index, False)

    def _emit_book_sync(self, market_index: int, synced: bool) -> None:
        self._book_synced[market_index] = synced
        if market_index != self._current_market_index:
            return
        self._broadcast({"type": "book_sync", "market_index": market_index, "synced": synced})

    def request_snapshot(self, market_index: int | None = None) -> None:
        mi = market_index if market_index is not None else self._current_market_index
        if mi is None or mi not in self._order_books:
            return
        self._queue_snapshot(mi)

    @staticmethod
    def _accumulate_delta(
        bucket: dict[int, dict[str, str]], market_index: int, levels: list[OrderBookLevel]
    ) -> None:
        side = bucket.setdefault(market_index, {})
        for lvl in levels:
            side[lvl.price] = lvl.size

    def _clear_pending_deltas(self, market_index: int) -> None:
        self._pending_delta_bids.pop(market_index, None)
        self._pending_delta_asks.pop(market_index, None)

    def _queue_snapshot(self, market_index: int) -> None:
        self._pending_snapshot.add(market_index)
        self._clear_pending_deltas(market_index)
        self._schedule_broadcast()

    def _queue_delta(
        self,
        market_index: int,
        bids: list[OrderBookLevel],
        asks: list[OrderBookLevel],
    ) -> None:
        if market_index in self._pending_snapshot:
            return
        if not bids and not asks:
            return
        self._accumulate_delta(self._pending_delta_bids, market_index, bids)
        self._accumulate_delta(self._pending_delta_asks, market_index, asks)
        self._schedule_broadcast()

    def _schedule_broadcast(self) -> None:
        task = self._book_flush_task
        if task is not None and not task.done():
            return
        self._book_flush_task = asyncio.create_task(self._flush_broadcasts())

    def delta_payload(
        self,
        market_index: int,
        bids: dict[str, str],
        asks: dict[str, str],
        timestamp: int | None,
    ) -> dict[str, Any]:
        prev, seq = self._next_book_seq(market_index)
        return {
            "type": "order_book_delta",
            "market_index": market_index,
            "seq": seq,
            "prev_seq": prev,
            "bids": [{"price": p, "size": s} for p, s in bids.items()],
            "asks": [{"price": p, "size": s} for p, s in asks.items()],
            "timestamp": timestamp,
        }

    async def _flush_broadcasts(self) -> None:
        await asyncio.sleep(BOOK_BROADCAST_MS)
        snapshots = self._pending_snapshot.copy()
        self._pending_snapshot.clear()
        delta_markets = set(self._pending_delta_bids) | set(self._pending_delta_asks)
        current = self._current_market_index

        for market_index in snapshots:
            self._clear_pending_deltas(market_index)
            if market_index != current:
                continue
            payload = self.order_book_payload(market_index, bump_seq=True)
            if payload:
                self._broadcast(payload)

        for market_index in delta_markets - snapshots:
            bids = self._pending_delta_bids.pop(market_index, {})
            asks = self._pending_delta_asks.pop(market_index, {})
            if not bids and not asks:
                continue
            if market_index != current:
                continue
            snap = self._order_books.get(market_index)
            self._broadcast(
                self.delta_payload(
                    market_index,
                    bids,
                    asks,
                    snap.timestamp if snap else None,
                )
            )

    async def _book_resync_loop(self, get_current: Callable[[], int | None]) -> None:
        while True:
            try:
                await asyncio.sleep(BOOK_RESYNC_S)
                mi = get_current()
                if mi is not None and mi in self._order_books:
                    self._queue_snapshot(mi)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("book resync loop error")

    async def handle_message(self, msg: dict[str, Any]) -> None:
        market_index = message_market_index(msg, "order_book")
        if market_index is None:
            market_index = self._current_market_index
        if market_index is None or not self._watched(market_index):
            logger.debug(
                "drop order_book market=%s current=%s pinned=%s type=%s",
                market_index,
                self._current_market_index,
                sorted(self._pinned),
                msg.get("type"),
            )
            return

        ob = msg.get("order_book", {}) or {}
        incoming_bids = self.parse_levels(ob.get("bids"))
        incoming_asks = self.parse_levels(ob.get("asks"))
        is_snapshot = msg.get("type") == "subscribed/order_book"
        prev = self._order_books.get(market_index)

        nonce = ob.get("nonce")
        begin_nonce = ob.get("begin_nonce")
        nonce_gap = False
        if (
            not is_snapshot
            and prev is not None
            and isinstance(nonce, int)
            and isinstance(begin_nonce, int)
        ):
            last = self._last_book_nonce.get(market_index)
            if last is not None and begin_nonce != last:
                nonce_gap = True
                logger.warning(
                    "order_book nonce gap market=%s last=%s begin=%s — forcing snapshot",
                    market_index,
                    last,
                    begin_nonce,
                )
        if isinstance(nonce, int):
            self._last_book_nonce[market_index] = nonce

        if nonce_gap:
            self._order_books.pop(market_index, None)
            self._last_book_nonce.pop(market_index, None)
            self._clear_pending_deltas(market_index)
            self._emit_book_sync(market_index, False)
            if self._resubscribe:
                self._resubscribe(market_index)
            return

        if is_snapshot or prev is None:
            snapshot = OrderBookSnapshot(
                market_index=market_index,
                bids=self.sorted_side(incoming_bids, bids=True),
                asks=self.sorted_side(incoming_asks, bids=False),
                timestamp=msg.get("timestamp"),
            )
            self._order_books[market_index] = snapshot
            if prev is None:
                logger.info(
                    "order_book snapshot market=%s bids=%d asks=%d",
                    market_index,
                    len(snapshot.bids),
                    len(snapshot.asks),
                )
            self._emit_book_sync(market_index, True)
            self._queue_snapshot(market_index)
            return

        snapshot = OrderBookSnapshot(
            market_index=market_index,
            bids=self.merge_side(prev.bids, incoming_bids, bids=True),
            asks=self.merge_side(prev.asks, incoming_asks, bids=False),
            timestamp=msg.get("timestamp"),
        )
        self._order_books[market_index] = snapshot
        self._queue_delta(market_index, incoming_bids, incoming_asks)
