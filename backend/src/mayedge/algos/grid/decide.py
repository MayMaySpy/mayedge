"""Pure planner for chase-grid — iceberg chase clips, lattice lots/TPs, merge, B/E."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from mayedge.algos.chase.iceberg import (
    Action,
    ChaseIcebergParams,
    MarketView,
    decide as chase_decide,
    round_passive,
)
from mayedge.algos.grid.config import DEFAULT_BE_BPS, MAX_UNMATCHED_TPS

ALGO_ID = "chase-grid"
ALGO_VERSION = "1"
BPS = Decimal("10000")

Side = Literal["buy", "sell"]
LotSide = Literal["long", "short"]
ClipKind = Literal["chase_buy", "chase_sell", "tp"]


class GridAction(StrEnum):
    REST = "rest"
    PAUSE = "pause"


@dataclass(frozen=True)
class GridParams:
    max_inventory: Decimal
    display_qty: Decimal
    offset_bps: Decimal
    profit_bps: Decimal
    grid_bps: Decimal
    price_floor: Decimal
    price_ceiling: Decimal
    be_delay_ms: int = 0
    be_bps: Decimal = Decimal(str(DEFAULT_BE_BPS))
    reentry_cooldown_ms: int = 30_000
    reentry_bps: Decimal = Decimal("4")
    post_be_cooldown_ms: int = 60_000

    def to_json(self) -> dict[str, Any]:
        from mayedge.numbers import fmt_decimal

        return {
            "max_inventory": fmt_decimal(self.max_inventory) or "0",
            "display_qty": fmt_decimal(self.display_qty) or "0",
            "offset_bps": fmt_decimal(self.offset_bps) or "0",
            "profit_bps": fmt_decimal(self.profit_bps) or "0",
            "grid_bps": fmt_decimal(self.grid_bps) or "0",
            "price_floor": fmt_decimal(self.price_floor) or "0",
            "price_ceiling": fmt_decimal(self.price_ceiling) or "0",
            "be_delay_ms": self.be_delay_ms,
            "be_bps": fmt_decimal(self.be_bps) or "0",
            "reentry_cooldown_ms": self.reentry_cooldown_ms,
            "reentry_bps": fmt_decimal(self.reentry_bps) or "0",
            "post_be_cooldown_ms": self.post_be_cooldown_ms,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> GridParams:
        return cls(
            max_inventory=Decimal(str(raw.get("max_inventory") or "0")),
            display_qty=Decimal(str(raw.get("display_qty") or "0")),
            offset_bps=Decimal(str(raw.get("offset_bps") or "4")),
            profit_bps=Decimal(str(raw.get("profit_bps") or "0")),
            grid_bps=Decimal(str(raw.get("grid_bps") or raw.get("profit_bps") or "0")),
            price_floor=Decimal(str(raw.get("price_floor") or "0")),
            price_ceiling=Decimal(str(raw.get("price_ceiling") or "0")),
            be_delay_ms=int(raw.get("be_delay_ms") or 0),
            be_bps=Decimal(str(raw["be_bps"])) if raw.get("be_bps") is not None else Decimal("0"),
            reentry_cooldown_ms=int(raw.get("reentry_cooldown_ms") or 30_000),
            reentry_bps=Decimal(str(raw.get("reentry_bps") or "4")),
            post_be_cooldown_ms=int(raw.get("post_be_cooldown_ms") or 60_000),
        )


@dataclass
class Lot:
    lot_id: str
    cell_price: Decimal
    qty: Decimal
    vwap: Decimal
    side: LotSide
    tp_price: Decimal
    tp_clip_seq: int | None = None
    opened_at: int = 0
    merged: bool = False

    @property
    def tp_side(self) -> Side:
        return "sell" if self.side == "long" else "buy"

    def to_json(self) -> dict[str, Any]:
        from mayedge.numbers import fmt_decimal

        return {
            "lot_id": self.lot_id,
            "cell_price": fmt_decimal(self.cell_price) or "0",
            "qty": fmt_decimal(self.qty) or "0",
            "vwap": fmt_decimal(self.vwap) or "0",
            "side": self.side,
            "tp_price": fmt_decimal(self.tp_price) or "0",
            "tp_clip_seq": self.tp_clip_seq,
            "opened_at": self.opened_at,
            "merged": self.merged,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Lot:
        return cls(
            lot_id=str(raw.get("lot_id") or uuid4().hex[:8]),
            cell_price=Decimal(str(raw.get("cell_price") or "0")),
            qty=Decimal(str(raw.get("qty") or "0")),
            vwap=Decimal(str(raw.get("vwap") or "0")),
            side=("long" if raw.get("side") == "long" else "short"),
            tp_price=Decimal(str(raw.get("tp_price") or "0")),
            tp_clip_seq=int(raw["tp_clip_seq"]) if raw.get("tp_clip_seq") is not None else None,
            opened_at=int(raw.get("opened_at") or 0),
            merged=bool(raw.get("merged")),
        )


@dataclass
class HotCell:
    cell_price: Decimal
    until_ms: int


@dataclass
class GridRuntime:
    inventory: Decimal = Decimal("0")
    inventory_vwap: Decimal | None = None
    lots: list[Lot] = field(default_factory=list)
    hot_cells: list[HotCell] = field(default_factory=list)
    reentry_until: int = 0
    grid_anchor: Decimal | None = None
    last_snapped_buy: Decimal | None = None
    last_snapped_sell: Decimal | None = None
    merged_active: bool = False
    merged_opened_at: int = 0
    clip_kinds: dict[int, str] = field(default_factory=dict)
    handled_fill_qty: dict[int, Decimal] = field(default_factory=dict)
    captured_pnl: Decimal = Decimal("0")

    def to_json(self) -> dict[str, Any]:
        return {
            "inventory": str(self.inventory),
            "inventory_vwap": str(self.inventory_vwap) if self.inventory_vwap is not None else None,
            "captured_pnl": str(self.captured_pnl),
            "lots": [lot.to_json() for lot in self.lots],
            "hot_cells": [
                {"cell_price": str(h.cell_price), "until_ms": h.until_ms} for h in self.hot_cells
            ],
            "reentry_until": self.reentry_until,
            "grid_anchor": str(self.grid_anchor) if self.grid_anchor is not None else None,
            "last_snapped_buy": (
                str(self.last_snapped_buy) if self.last_snapped_buy is not None else None
            ),
            "last_snapped_sell": (
                str(self.last_snapped_sell) if self.last_snapped_sell is not None else None
            ),
            "merged_active": self.merged_active,
            "merged_opened_at": self.merged_opened_at,
            "clip_kinds": {str(k): v for k, v in self.clip_kinds.items()},
            "handled_fill_qty": {str(k): str(v) for k, v in self.handled_fill_qty.items()},
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> GridRuntime:
        hot: list[HotCell] = []
        for item in raw.get("hot_cells") or []:
            if isinstance(item, dict):
                hot.append(
                    HotCell(
                        cell_price=Decimal(str(item.get("cell_price") or "0")),
                        until_ms=int(item.get("until_ms") or 0),
                    )
                )
        kinds_raw = raw.get("clip_kinds") or {}
        clip_kinds = (
            {int(k): str(v) for k, v in kinds_raw.items()} if isinstance(kinds_raw, dict) else {}
        )
        handled_raw = raw.get("handled_fill_qty") or {}
        handled_fill_qty = (
            {int(k): Decimal(str(v)) for k, v in handled_raw.items()}
            if isinstance(handled_raw, dict)
            else {}
        )
        inv_vwap = raw.get("inventory_vwap")
        anchor = raw.get("grid_anchor")
        last_buy = raw.get("last_snapped_buy")
        last_sell = raw.get("last_snapped_sell")
        return cls(
            inventory=Decimal(str(raw.get("inventory") or "0")),
            inventory_vwap=Decimal(str(inv_vwap)) if inv_vwap is not None else None,
            lots=[
                Lot.from_json(item) for item in (raw.get("lots") or []) if isinstance(item, dict)
            ],
            hot_cells=hot,
            reentry_until=int(raw.get("reentry_until") or 0),
            grid_anchor=Decimal(str(anchor)) if anchor is not None else None,
            last_snapped_buy=Decimal(str(last_buy)) if last_buy is not None else None,
            last_snapped_sell=Decimal(str(last_sell)) if last_sell is not None else None,
            merged_active=bool(raw.get("merged_active")),
            merged_opened_at=int(raw.get("merged_opened_at") or 0),
            clip_kinds=clip_kinds,
            handled_fill_qty=handled_fill_qty,
            captured_pnl=Decimal(str(raw.get("captured_pnl") or "0")),
        )


@dataclass(frozen=True)
class SideQuote:
    action: GridAction
    price: Decimal | None = None
    qty: Decimal | None = None
    reason: str | None = None


@dataclass(frozen=True)
class TpTarget:
    lot_id: str
    side: Side
    price: Decimal
    qty: Decimal


@dataclass(frozen=True)
class BeFlatten:
    side: Side
    qty: Decimal
    vwap: Decimal


@dataclass(frozen=True)
class GridPlan:
    buy: SideQuote | None
    sell: SideQuote | None
    tps: tuple[TpTarget, ...]
    cancel_lot_ids: tuple[str, ...]
    be: BeFlatten | None
    quote_action: str
    reason: str | None


def grid_step(anchor: Decimal, grid_bps: Decimal) -> Decimal:
    if anchor <= 0 or grid_bps <= 0:
        return Decimal("0")
    return anchor * grid_bps / BPS


def snap_to_grid(
    price: Decimal,
    *,
    anchor: Decimal,
    grid_bps: Decimal,
    tick: Decimal,
    side: Side,
) -> Decimal:
    step = grid_step(anchor, grid_bps)
    if step <= 0:
        return round_passive(price, tick, side)
    offset = (price - anchor) / step
    if side == "buy":
        cell = offset.to_integral_value(rounding=ROUND_DOWN)
    else:
        cell = offset.to_integral_value(rounding=ROUND_UP)
    snapped = anchor + cell * step
    return round_passive(snapped, tick, side)


def tp_price_for_lot(vwap: Decimal, side: LotSide, profit_bps: Decimal, tick: Decimal) -> Decimal:
    profit = profit_bps / BPS
    if side == "long":
        raw = vwap * (Decimal("1") + profit)
        return round_passive(raw, tick, "sell")
    raw = vwap * (Decimal("1") - profit)
    return round_passive(raw, tick, "buy")


def be_price(vwap: Decimal, side: LotSide, be_bps: Decimal) -> Decimal:
    buf = be_bps / BPS
    if side == "long":
        return vwap * (Decimal("1") + buf)
    return vwap * (Decimal("1") - buf)


def _chase_side_quote(
    side: Side,
    params: GridParams,
    market: MarketView,
    *,
    clip_qty: Decimal,
) -> SideQuote:
    """Chase-iceberg clip behind the touch. Lattice is for lots/TPs, not this price."""
    chase_params = ChaseIcebergParams(
        side=side,
        qty=clip_qty,
        display_qty=clip_qty,
        offset_bps=params.offset_bps,
        price_floor=params.price_floor,
        price_ceiling=params.price_ceiling,
    )
    q = chase_decide(chase_params, market, remaining=clip_qty)
    if q.action != Action.REST or q.price is None or q.qty is None:
        return SideQuote(GridAction.PAUSE, reason=q.reason)
    return SideQuote(GridAction.REST, price=q.price, qty=q.qty, reason=None)


def _hot_cell_blocks(
    side: Side, price: Decimal, runtime: GridRuntime, params: GridParams, now: int
) -> bool:
    if now < runtime.reentry_until:
        return True
    tol = grid_step(price, params.reentry_bps) if price > 0 else Decimal("0")
    for hot in runtime.hot_cells:
        if now >= hot.until_ms:
            continue
        if tol <= 0:
            if hot.cell_price == price:
                return True
        elif abs(hot.cell_price - price) <= tol:
            return True
    return False


def _open_tp_lots(runtime: GridRuntime) -> list[Lot]:
    return [lot for lot in runtime.lots if lot.qty > 0 and not lot.merged]


def merge_lots(lots: list[Lot], *, profit_bps: Decimal, tick: Decimal, now: int) -> Lot:
    total_qty = sum((lot.qty for lot in lots), Decimal("0"))
    vwap = sum((lot.vwap * lot.qty for lot in lots), Decimal("0")) / total_qty
    side: LotSide = "long" if lots[0].side == "long" else "short"
    if any(lot.side != side for lot in lots):
        # Mixed inventory should not happen; prefer net side from qty sign.
        long_qty = sum((lot.qty for lot in lots if lot.side == "long"), Decimal("0"))
        short_qty = sum((lot.qty for lot in lots if lot.side == "short"), Decimal("0"))
        side = "long" if long_qty >= short_qty else "short"
    cell = lots[0].cell_price
    tp_px = tp_price_for_lot(vwap, side, profit_bps, tick)
    return Lot(
        lot_id=f"merged-{uuid4().hex[:8]}",
        cell_price=cell,
        qty=total_qty,
        vwap=vwap,
        side=side,
        tp_price=tp_px,
        opened_at=now,
        merged=True,
    )


def add_fill_to_lots(
    runtime: GridRuntime,
    *,
    side: Side,
    fill_qty: Decimal,
    fill_vwap: Decimal,
    params: GridParams,
    market: MarketView,
    now: int,
) -> None:
    anchor = runtime.grid_anchor or fill_vwap
    runtime.grid_anchor = anchor
    cell = snap_to_grid(
        fill_vwap,
        anchor=anchor,
        grid_bps=params.grid_bps,
        tick=market.tick,
        side=side,
    )
    lot_side: LotSide = "long" if side == "buy" else "short"
    runtime.lots.append(
        Lot(
            lot_id=uuid4().hex[:8],
            cell_price=cell,
            qty=fill_qty,
            vwap=fill_vwap,
            side=lot_side,
            tp_price=tp_price_for_lot(fill_vwap, lot_side, params.profit_bps, market.tick),
            opened_at=now,
        )
    )


def align_runtime_to_position(
    runtime: GridRuntime,
    *,
    venue_size: Decimal,
    entry: Decimal | None,
    params: GridParams,
    market: MarketView,
    now: int,
) -> None:
    """Snap lots + inventory to the venue position. Clip fills can drift; the book cannot."""
    want_qty = abs(venue_size)
    want_side: LotSide | None = None if venue_size == 0 else ("long" if venue_size > 0 else "short")
    matching = (
        sum(
            (lot.qty for lot in runtime.lots if want_side is not None and lot.side == want_side),
            Decimal("0"),
        )
        if want_side is not None
        else Decimal("0")
    )
    extras = any(
        lot.qty > 0 and (want_side is None or lot.side != want_side) for lot in runtime.lots
    )
    if runtime.inventory == venue_size and matching == want_qty and not extras:
        return

    runtime.inventory = venue_size
    runtime.inventory_vwap = entry if venue_size != 0 else None
    if venue_size == 0 or want_side is None:
        runtime.lots = []
        runtime.merged_active = False
        return

    runtime.lots = [lot for lot in runtime.lots if lot.side == want_side and lot.qty > 0]
    have = sum((lot.qty for lot in runtime.lots), Decimal("0"))
    if have > want_qty:
        reduce_lots(
            runtime,
            close_side=want_side,
            qty=have - want_qty,
            now=now,
            reentry_cooldown_ms=0,
            fill_vwap=None,
        )
        have = sum((lot.qty for lot in runtime.lots), Decimal("0"))
    if have < want_qty:
        px = entry or runtime.inventory_vwap
        if px is None or px <= 0:
            px = (market.bid if want_side == "long" else market.ask) or Decimal("0")
        add_fill_to_lots(
            runtime,
            side="buy" if want_side == "long" else "sell",
            fill_qty=want_qty - have,
            fill_vwap=px,
            params=params,
            market=market,
            now=now,
        )
    runtime.inventory = venue_size
    if entry is not None and entry > 0:
        runtime.inventory_vwap = entry


def apply_inventory_delta(
    runtime: GridRuntime,
    *,
    delta: Decimal,
    fill_price: Decimal,
) -> None:
    prev = runtime.inventory
    new_inv = prev + delta
    if prev == 0 or (prev > 0 and delta > 0) or (prev < 0 and delta < 0):
        # Adding to same direction — update VWAP.
        if new_inv == 0:
            runtime.inventory_vwap = None
        elif prev == 0:
            runtime.inventory_vwap = fill_price
        else:
            runtime.inventory_vwap = (
                abs(prev) * (runtime.inventory_vwap or fill_price) + abs(delta) * fill_price
            ) / abs(new_inv)
    elif new_inv == 0:
        runtime.inventory_vwap = None
    elif (prev > 0 > new_inv) or (prev < 0 < new_inv):
        runtime.inventory_vwap = fill_price
    runtime.inventory = new_inv


def lot_close_pnl(lot: Lot, qty: Decimal, close_px: Decimal) -> Decimal:
    """Gross quote PnL from closing `qty` of `lot` at `close_px`."""
    if qty <= 0:
        return Decimal("0")
    if lot.side == "long":
        return (close_px - lot.vwap) * qty
    return (lot.vwap - close_px) * qty


def _credit_close(runtime: GridRuntime, lot: Lot, qty: Decimal, close_px: Decimal | None) -> None:
    if close_px is None or qty <= 0:
        return
    runtime.captured_pnl += lot_close_pnl(lot, qty, close_px)


def reduce_lots(
    runtime: GridRuntime,
    *,
    close_side: LotSide,
    qty: Decimal,
    now: int,
    reentry_cooldown_ms: int,
    fill_vwap: Decimal | None = None,
) -> Decimal:
    """FIFO-close lots on close_side. Returns qty not absorbed (flip remainder)."""
    leftover = qty
    keep: list[Lot] = []
    for lot in runtime.lots:
        if leftover <= 0 or lot.side != close_side or lot.qty <= 0:
            if lot.qty > 0:
                keep.append(lot)
            continue
        take = min(lot.qty, leftover)
        _credit_close(runtime, lot, take, fill_vwap)
        lot.qty -= take
        leftover -= take
        runtime.hot_cells.append(
            HotCell(cell_price=lot.cell_price, until_ms=now + reentry_cooldown_ms)
        )
        if lot.qty > 0:
            keep.append(lot)
        elif lot.merged:
            runtime.merged_active = False
    runtime.lots = keep
    return leftover


def apply_chase_fill(
    runtime: GridRuntime,
    *,
    side: Side,
    fill_qty: Decimal,
    fill_vwap: Decimal,
    params: GridParams,
    market: MarketView,
    now: int,
) -> None:
    """Adding fill opens a lot; reducing fill FIFO-closes opposite lots (no stacked shorts on longs)."""
    inv = runtime.inventory
    reducing = (side == "sell" and inv > 0) or (side == "buy" and inv < 0)
    delta = fill_qty if side == "buy" else -fill_qty
    if reducing:
        close_side: LotSide = "long" if side == "sell" else "short"
        leftover = reduce_lots(
            runtime,
            close_side=close_side,
            qty=fill_qty,
            now=now,
            reentry_cooldown_ms=params.reentry_cooldown_ms,
            fill_vwap=fill_vwap,
        )
        apply_inventory_delta(runtime, delta=delta, fill_price=fill_vwap)
        if leftover > 0:
            add_fill_to_lots(
                runtime,
                side=side,
                fill_qty=leftover,
                fill_vwap=fill_vwap,
                params=params,
                market=market,
                now=now,
            )
        return
    add_fill_to_lots(
        runtime,
        side=side,
        fill_qty=fill_qty,
        fill_vwap=fill_vwap,
        params=params,
        market=market,
        now=now,
    )
    apply_inventory_delta(runtime, delta=delta, fill_price=fill_vwap)


def credit_tp_fill(
    runtime: GridRuntime,
    *,
    side: Side,
    qty: Decimal,
    fill_vwap: Decimal,
    params: GridParams,
    now: int,
    lot: Lot | None = None,
) -> None:
    """Close inventory on a profit fill. Prefer the lot that owned the TP."""
    leftover = qty
    if lot is not None and lot.qty > 0:
        take = min(lot.qty, leftover)
        _credit_close(runtime, lot, take, fill_vwap)
        lot.qty -= take
        leftover -= take
        runtime.hot_cells.append(
            HotCell(cell_price=lot.cell_price, until_ms=now + params.reentry_cooldown_ms)
        )
        if lot.qty <= 0:
            runtime.lots = [item for item in runtime.lots if item.lot_id != lot.lot_id]
            if lot.merged:
                runtime.merged_active = False
                runtime.reentry_until = now + params.post_be_cooldown_ms
    if leftover > 0:
        close_side: LotSide = "long" if side == "sell" else "short"
        reduce_lots(
            runtime,
            close_side=close_side,
            qty=leftover,
            now=now,
            reentry_cooldown_ms=params.reentry_cooldown_ms,
            fill_vwap=fill_vwap,
        )
    apply_inventory_delta(runtime, delta=-qty if side == "sell" else qty, fill_price=fill_vwap)


def credit_grid_fill(
    runtime: GridRuntime,
    *,
    kind: str | None,
    side: Side,
    qty: Decimal,
    fill_vwap: Decimal,
    params: GridParams,
    market: MarketView,
    now: int,
    lot: Lot | None = None,
) -> None:
    """Apply a closed (or newly seen) clip fill to lots + inventory."""
    if qty <= 0:
        return
    if kind == "tp" or lot is not None:
        credit_tp_fill(
            runtime, side=side, qty=qty, fill_vwap=fill_vwap, params=params, now=now, lot=lot
        )
        return
    apply_chase_fill(
        runtime, side=side, fill_qty=qty, fill_vwap=fill_vwap, params=params, market=market, now=now
    )


def decide(
    params: GridParams,
    market: MarketView,
    runtime: GridRuntime,
    *,
    now: int,
) -> GridPlan:
    bid = market.bid
    ask = market.ask
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return GridPlan(None, None, (), (), None, Action.PAUSE.value, "no_book")
    if params.price_floor >= params.price_ceiling:
        return GridPlan(None, None, (), (), None, Action.PAUSE.value, "invalid_band")

    mid = (bid + ask) / 2
    anchor = runtime.grid_anchor or mid
    runtime.grid_anchor = anchor

    inv = runtime.inventory
    cap = params.max_inventory

    # Chase only adds. Reducing is TPs only — a tight chase on the close side
    # would fill first and burn the profit order.
    buy_adding = inv >= 0 and inv < cap
    sell_adding = inv <= 0 and inv > -cap

    buy_q: SideQuote | None = None
    sell_q: SideQuote | None = None

    if buy_adding:
        clip = min(params.display_qty, cap - inv)
        if clip >= market.min_qty:
            buy_q = _chase_side_quote("buy", params, market, clip_qty=clip)
            if buy_q.action == GridAction.REST and buy_q.price is not None:
                if _hot_cell_blocks("buy", buy_q.price, runtime, params, now):
                    buy_q = SideQuote(GridAction.PAUSE, reason="reentry_cooldown")
        else:
            buy_q = SideQuote(GridAction.PAUSE, reason="below_min_qty")
    elif inv < 0:
        buy_q = SideQuote(GridAction.PAUSE, reason="tp_covers")
    else:
        buy_q = SideQuote(GridAction.PAUSE, reason="inventory_cap")

    if sell_adding:
        clip = min(params.display_qty, cap + inv)
        if clip >= market.min_qty:
            sell_q = _chase_side_quote("sell", params, market, clip_qty=clip)
            if sell_q.action == GridAction.REST and sell_q.price is not None:
                if _hot_cell_blocks("sell", sell_q.price, runtime, params, now):
                    sell_q = SideQuote(GridAction.PAUSE, reason="reentry_cooldown")
        else:
            sell_q = SideQuote(GridAction.PAUSE, reason="below_min_qty")
    elif inv > 0:
        sell_q = SideQuote(GridAction.PAUSE, reason="tp_covers")
    else:
        sell_q = SideQuote(GridAction.PAUSE, reason="inventory_cap")

    unmatched = _open_tp_lots(runtime)
    cancel_ids: list[str] = []
    tps: list[TpTarget] = []
    be: BeFlatten | None = None

    if len(unmatched) > MAX_UNMATCHED_TPS:
        to_merge = [lot for lot in runtime.lots if lot.qty > 0]
        merged = merge_lots(to_merge, profit_bps=params.profit_bps, tick=market.tick, now=now)
        cancel_ids = [lot.lot_id for lot in to_merge]
        runtime.lots = [lot for lot in runtime.lots if lot.lot_id not in cancel_ids]
        runtime.lots.append(merged)
        runtime.merged_active = True
        runtime.merged_opened_at = now

    for lot in runtime.lots:
        if lot.qty <= 0:
            continue
        qty = min(lot.qty, abs(inv)) if inv != 0 else lot.qty
        if qty < market.min_qty:
            continue
        tps.append(
            TpTarget(
                lot_id=lot.lot_id,
                side=lot.tp_side,
                price=lot.tp_price,
                qty=qty,
            )
        )

    if runtime.merged_active and params.be_delay_ms > 0:
        merged_lots = [lot for lot in runtime.lots if lot.merged and lot.qty > 0]
        if merged_lots:
            lot = merged_lots[0]
            age_ok = now - runtime.merged_opened_at >= params.be_delay_ms
            be_px = be_price(lot.vwap, lot.side, params.be_bps)
            if lot.side == "long":
                at_be = mid >= be_px
                flatten_side: Side = "sell"
            else:
                at_be = mid <= be_px
                flatten_side = "buy"
            if age_ok and at_be and lot.qty >= market.min_qty:
                be = BeFlatten(side=flatten_side, qty=min(lot.qty, abs(inv)), vwap=lot.vwap)

    resting = (
        (buy_q is not None and buy_q.action == GridAction.REST)
        or (sell_q is not None and sell_q.action == GridAction.REST)
        or bool(tps)
    )
    quote_action = Action.REST.value if resting else Action.PAUSE.value
    reason = None
    if not resting:
        reason = (
            (buy_q.reason if buy_q else None) or (sell_q.reason if sell_q else None) or "waiting"
        )

    return GridPlan(
        buy=buy_q,
        sell=sell_q,
        tps=tuple(tps),
        cancel_lot_ids=tuple(cancel_ids),
        be=be,
        quote_action=quote_action,
        reason=reason,
    )
