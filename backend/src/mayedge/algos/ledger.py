from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from mayedge.numbers import fmt_decimal

ClipStatus = Literal["live", "filled", "cancelled"]
ClipSide = Literal["buy", "sell"]


def _fmt(d: Decimal | None) -> str | None:
    return fmt_decimal(d)


@dataclass
class Clip:
    seq: int
    client_order_index: int
    price: Decimal
    qty: Decimal
    filled: Decimal = Decimal("0")
    order_index: int | None = None
    side: ClipSide | None = None
    status: ClipStatus = "live"
    seen_on_book: bool = False
    placed_at: int = 0
    closed_at: int | None = None
    # When the child first disappeared from the open-order cache while still
    # "live" in the ledger. Used to wait for trades before assuming a fill.
    missing_since: int | None = None

    @property
    def remaining(self) -> Decimal:
        return max(Decimal("0"), self.qty - self.filled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "client_order_index": str(self.client_order_index),
            "order_index": str(self.order_index) if self.order_index is not None else None,
            "side": self.side,
            "price": _fmt(self.price),
            "qty": _fmt(self.qty),
            "filled": _fmt(self.filled),
            "remaining": _fmt(self.remaining),
            "status": self.status,
            "seen_on_book": self.seen_on_book,
            "placed_at": self.placed_at,
            "closed_at": self.closed_at,
            "missing_since": self.missing_since,
        }

    def to_persist(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "client_order_index": self.client_order_index,
            "order_index": self.order_index,
            "side": self.side,
            "price": _fmt(self.price) or "0",
            "qty": _fmt(self.qty) or "0",
            "filled": _fmt(self.filled) or "0",
            "status": self.status,
            "seen_on_book": self.seen_on_book,
            "placed_at": self.placed_at,
            "closed_at": self.closed_at,
            "missing_since": self.missing_since,
        }

    @classmethod
    def from_persist(cls, raw: dict[str, Any]) -> Clip:
        status = raw.get("status") or "live"
        if status not in ("live", "filled", "cancelled"):
            status = "live"
        return cls(
            seq=int(raw["seq"]),
            client_order_index=int(raw["client_order_index"]),
            order_index=int(raw["order_index"]) if raw.get("order_index") is not None else None,
            side=raw.get("side") if raw.get("side") in ("buy", "sell") else None,
            price=Decimal(str(raw["price"])),
            qty=Decimal(str(raw["qty"])),
            filled=Decimal(str(raw.get("filled") or "0")),
            status=status,  # type: ignore[arg-type]
            seen_on_book=bool(raw.get("seen_on_book")),
            placed_at=int(raw.get("placed_at") or 0),
            closed_at=int(raw["closed_at"]) if raw.get("closed_at") is not None else None,
            missing_since=(
                int(raw["missing_since"]) if raw.get("missing_since") is not None else None
            ),
        )


@dataclass
class Fill:
    seq: int
    clip_seq: int
    price: Decimal
    qty: Decimal
    ts: int
    order_index: int | None = None
    client_order_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "clip_seq": self.clip_seq,
            "price": _fmt(self.price),
            "qty": _fmt(self.qty),
            "ts": self.ts,
            "order_index": str(self.order_index) if self.order_index is not None else None,
            "client_order_index": (
                str(self.client_order_index) if self.client_order_index is not None else None
            ),
        }

    def to_persist(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "clip_seq": self.clip_seq,
            "price": _fmt(self.price) or "0",
            "qty": _fmt(self.qty) or "0",
            "ts": self.ts,
            "order_index": self.order_index,
            "client_order_index": self.client_order_index,
        }

    @classmethod
    def from_persist(cls, raw: dict[str, Any]) -> Fill:
        return cls(
            seq=int(raw["seq"]),
            clip_seq=int(raw["clip_seq"]),
            price=Decimal(str(raw["price"])),
            qty=Decimal(str(raw["qty"])),
            ts=int(raw["ts"]),
            order_index=int(raw["order_index"]) if raw.get("order_index") is not None else None,
            client_order_index=(
                int(raw["client_order_index"])
                if raw.get("client_order_index") is not None
                else None
            ),
        )


@dataclass
class Ledger:
    """Master algo order: clips (venue children) and fills against them."""

    clips: list[Clip] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    next_clip: int = 1
    next_fill: int = 1
    trade_ids: set[int] = field(default_factory=set)
    trade_qty_by_clip: dict[int, Decimal] = field(default_factory=dict)

    def working(self) -> Clip | None:
        for c in reversed(self.clips):
            if c.status == "live":
                return c
        return None

    def working_side(self, side: ClipSide) -> Clip | None:
        for c in reversed(self.clips):
            if c.status == "live" and c.side == side:
                return c
        return None

    def live_clips(self) -> list[Clip]:
        return [c for c in self.clips if c.status == "live"]

    def working_filled_total(self) -> Decimal:
        """Master progress: per-clip filled capped at clip qty (not raw fill events)."""
        return sum((min(c.filled, c.qty) for c in self.clips), Decimal("0"))

    def filled_total(self) -> Decimal:
        """Sum of blotter fill events (may exceed working_filled_total if paths overlap)."""
        return sum((f.qty for f in self.fills), Decimal("0"))

    def has_fill_evidence(self, clip: Clip) -> bool:
        """True if trades or open-order sync already credited something on this clip."""
        if clip.filled > 0:
            return True
        return self.trade_qty_by_clip.get(clip.seq, Decimal("0")) > 0

    def should_fill_when_missing(self, clip: Clip) -> bool:
        """True when we already know the clip is fully done (trades / open sync)."""
        if clip.remaining <= 0:
            return True
        traded = self.trade_qty_by_clip.get(clip.seq, Decimal("0"))
        if traded >= clip.qty:
            return True
        if clip.filled >= clip.qty:
            return True
        return False

    def amend(self, clip: Clip, *, price: Decimal, now: int) -> None:
        """Update a live clip in place after L2ModifyOrder (price-only)."""
        if clip.status != "live":
            return
        clip.price = price
        clip.placed_at = now
        clip.missing_since = None

    def place(
        self,
        *,
        client_order_index: int,
        price: Decimal,
        qty: Decimal,
        now: int,
        order_index: int | None = None,
        side: ClipSide | None = None,
    ) -> Clip:
        clip = Clip(
            seq=self.next_clip,
            client_order_index=client_order_index,
            order_index=order_index,
            side=side,
            price=price,
            qty=qty,
            placed_at=now,
        )
        self.next_clip += 1
        self.clips.append(clip)
        return clip

    def find_clip(
        self,
        *,
        client_order_index: int | None = None,
        order_index: int | None = None,
    ) -> Clip | None:
        for c in reversed(self.clips):
            if client_order_index and c.client_order_index == client_order_index:
                return c
            if order_index and c.order_index == order_index:
                return c
        return None

    def apply_open(
        self,
        clip: Clip,
        book_remaining: Decimal,
        *,
        now: int,
        order_index: int | None = None,
        book_filled: Decimal | None = None,
    ) -> Decimal:
        """Clip is still on the book. Returns fill delta."""
        clip.seen_on_book = True
        clip.missing_since = None
        if order_index:
            clip.order_index = order_index
        if book_filled is not None and book_filled > clip.filled:
            delta = min(book_filled - clip.filled, clip.qty - clip.filled)
        else:
            rem = max(Decimal("0"), book_remaining)
            if rem > clip.remaining:
                rem = clip.remaining
            delta = clip.remaining - rem
        if delta > 0:
            self._fill(clip, delta, now)
        if clip.remaining <= 0 and clip.status == "live":
            clip.status = "filled"
            clip.closed_at = now
        return delta

    def apply_trade(
        self,
        clip: Clip,
        qty: Decimal,
        *,
        now: int,
        price: Decimal | None = None,
        trade_id: int | None = None,
        order_index: int | None = None,
    ) -> Decimal:
        """Credit venue trades without double-counting open-order sync."""
        if trade_id:
            if trade_id in self.trade_ids:
                return Decimal("0")
            self.trade_ids.add(trade_id)
        if order_index:
            clip.order_index = order_index
        clip.seen_on_book = True
        q = max(Decimal("0"), qty)
        if q <= 0:
            return Decimal("0")
        traded = self.trade_qty_by_clip.get(clip.seq, Decimal("0")) + q
        self.trade_qty_by_clip[clip.seq] = traded
        # Watermark: whichever source (trades vs open sync) is ahead wins.
        target = min(clip.qty, max(clip.filled, traded))
        delta = target - clip.filled
        if delta <= 0:
            return Decimal("0")
        self._fill(clip, delta, now, price=price)
        if clip.remaining <= 0 and clip.status == "live":
            clip.status = "filled"
            clip.closed_at = now
        return delta

    def close_missing(self, clip: Clip, *, canceling: bool, now: int) -> Decimal:
        """Clip left the book. Cancel / unacked clip does not fill the remainder."""
        if clip.status != "live":
            return Decimal("0")
        if canceling:
            clip.status = "cancelled"
            clip.closed_at = now
            return Decimal("0")
        if not clip.seen_on_book:
            return Decimal("0")
        delta = clip.remaining
        if delta > 0:
            self._fill(clip, delta, now)
        clip.status = "filled"
        clip.closed_at = now
        return delta

    def _fill(
        self,
        clip: Clip,
        qty: Decimal,
        now: int,
        *,
        price: Decimal | None = None,
    ) -> Fill:
        clip.filled += qty
        rec = Fill(
            seq=self.next_fill,
            clip_seq=clip.seq,
            price=price if price is not None else clip.price,
            qty=qty,
            ts=now,
            order_index=clip.order_index,
            client_order_index=clip.client_order_index,
        )
        self.next_fill += 1
        self.fills.append(rec)
        return rec

    def to_dict(self) -> dict[str, Any]:
        live = self.working()
        live_bid = self.working_side("buy")
        live_ask = self.working_side("sell")
        return {
            "clips": [c.to_dict() for c in self.clips],
            "fills": [f.to_dict() for f in self.fills],
            "working": live.to_dict() if live else None,
            "working_bid": live_bid.to_dict() if live_bid else None,
            "working_ask": live_ask.to_dict() if live_ask else None,
        }

    def to_persist(self) -> dict[str, Any]:
        return {
            "next_clip": self.next_clip,
            "next_fill": self.next_fill,
            "trade_ids": set(self.trade_ids),
            "trade_qty_by_clip": {
                seq: (_fmt(qty) or "0") for seq, qty in self.trade_qty_by_clip.items()
            },
            "clips": [c.to_persist() for c in self.clips],
            "fills": [f.to_persist() for f in self.fills],
        }

    @classmethod
    def from_persist(cls, raw: dict[str, Any]) -> Ledger:
        ledger = cls(
            next_clip=int(raw.get("next_clip") or 1),
            next_fill=int(raw.get("next_fill") or 1),
            trade_ids={int(t) for t in (raw.get("trade_ids") or set())},
            trade_qty_by_clip={
                int(k): Decimal(str(v)) for k, v in (raw.get("trade_qty_by_clip") or {}).items()
            },
            clips=[Clip.from_persist(c) for c in (raw.get("clips") or [])],
            fills=[Fill.from_persist(f) for f in (raw.get("fills") or [])],
        )
        if ledger.clips:
            ledger.next_clip = max(ledger.next_clip, max(c.seq for c in ledger.clips) + 1)
        if ledger.fills:
            ledger.next_fill = max(ledger.next_fill, max(f.seq for f in ledger.fills) + 1)
        return ledger
