"""A fake venue for Planner job tests: a book of orders and one Position that fills move."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from venue_harness import FakeClock

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.planner.config import PLANNER_COI_BASE
from mayedge.algos.planner.job import PlannerRunner
from mayedge.lighter.models import MarketMeta

__all__ = ["MI", "FakeBook", "FakeClock", "FakeVenue", "eth"]

MI = 1


def eth() -> MarketMeta:
    return MarketMeta(
        market_index=MI,
        symbol="ETH",
        price_decimals=2,
        size_decimals=1,
        min_base_amount=0.1,
        min_quote_amount=0.0,
        last_trade_price=100.0,
        mark_price=100.0,
    )


@dataclass
class FakeVenue:
    meta: MarketMeta = field(default_factory=eth)
    position: Decimal = Decimal("0")
    entry: Decimal = Decimal("0")
    orders: dict[int, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    next_oid: int = 500
    bid: str = "99.9"
    ask: str = "100.1"

    # ── what the job reads ──
    def payload(self) -> dict[str, Any]:
        positions = []
        if self.position != 0:
            positions.append(
                {
                    "market_index": MI,
                    "size": str(self.position),
                    "entry_price": str(self.entry),
                    "liquidation_price": "",
                }
            )
        return {
            "positions": positions,
            "open_orders": list(self.orders.values()),
            "portfolio_margin": "10000",
            "taker_fee_bps": "0",
        }

    def set_mark(self, px: str) -> None:
        self.meta.mark_price = float(px)
        self.meta.last_trade_price = float(px)

    # ── what the job sends ──
    def _rest(
        self, coi: int, *, side: str, size: str, price: str, order_type: str, trigger: str = ""
    ) -> None:
        self.next_oid += 1
        self.orders[coi] = {
            "order_index": str(self.next_oid),
            "client_order_index": str(coi),
            "market_index": MI,
            "side": side,
            "price": price,
            "size": size,
            "remaining": size,
            "filled": "0",
            "order_type": order_type,
            "reduce_only": order_type != "limit",
            "trigger_price": trigger,
        }

    async def create_limit_order(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("limit", kw))
        px = Decimal(kw["price"])
        crosses = px >= Decimal(self.ask) if kw["side"] == "buy" else px <= Decimal(self.bid)
        if kw.get("time_in_force") == "post_only" and crosses:
            raise ValueError("post-only order would cross")
        self._rest(
            kw["client_order_index"],
            side=kw["side"],
            size=kw["size"],
            price=kw["price"],
            order_type="limit",
        )
        return {"tx_hash": "0x", "client_order_index": kw["client_order_index"]}

    async def modify_order(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("modify", kw))
        for row in self.orders.values():
            if int(row["order_index"]) == kw["order_index"]:
                row["price"] = kw["price"]
        return {"tx_hash": "0x"}

    async def create_market_order(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("market", kw))
        return {"tx_hash": "0x", "client_order_index": kw["client_order_index"]}

    async def create_trigger_leg(
        self, market_index: int, side: str, size: str, **kw: Any
    ) -> dict[str, Any]:
        self._check_side(side, kw["role"], Decimal(kw["trigger"]))
        self.calls.append((f"trigger_{kw['role']}", {"side": side, "size": size, **kw}))
        order_type = "stop-loss" if kw["role"] == "sl" else "take-profit-limit"
        self._rest(
            kw["client_order_index"],
            side=side,
            size=size,
            price=kw.get("price") or kw["trigger"],
            order_type=order_type,
            trigger=kw["trigger"],
        )
        return {"tx_hash": "0x", "client_order_index": kw["client_order_index"]}

    async def amend_trigger_leg(
        self, market_index: int, order_index: int, side: str, **kw: Any
    ) -> dict[str, Any]:
        self._check_side(side, kw["role"], Decimal(kw["trigger"]))
        self.calls.append(("amend", {"order_index": order_index, **kw}))
        for row in self.orders.values():
            if int(row["order_index"]) == order_index:
                row["trigger_price"] = kw["trigger"]
        return {"tx_hash": "0x"}

    async def cancel_order(self, market_index: int, order_index: int) -> dict[str, Any]:
        self.calls.append(("cancel", {"order_index": order_index}))
        for coi, row in list(self.orders.items()):
            if int(row["order_index"]) == order_index:
                del self.orders[coi]
        return {"tx_hash": "0x"}

    def _check_side(self, side: str, role: str, trigger: Decimal) -> None:
        mark = Decimal(str(self.meta.mark_price))
        is_ask = side == "sell"
        ok = (
            (trigger < mark if is_ask else trigger > mark)
            if role == "sl"
            else (trigger > mark if is_ask else trigger < mark)
        )
        if not ok:
            raise ValueError("Stop trigger is on the wrong side of mark")

    # ── what the market does ──
    def fill(self, coi: int, qty: str, *, price: str | None = None) -> None:
        """Fill part of a resting order and move the Position by it."""
        row = self.orders[coi]
        q = Decimal(qty)
        px = Decimal(price or row["price"])
        rem = Decimal(row["remaining"]) - q
        row["remaining"] = str(rem)
        row["filled"] = str(Decimal(row["filled"]) + q)
        if rem <= 0:
            del self.orders[coi]
        self.move(q if row["side"] == "buy" else -q, px)

    def move(self, delta: Decimal | str, px: Decimal | str) -> None:
        delta = Decimal(str(delta))
        px = Decimal(str(px))
        before = self.position
        after = before + delta
        if before == 0 or (before > 0) == (delta > 0):
            total = abs(before) + abs(delta)
            self.entry = (abs(before) * self.entry + abs(delta) * px) / total
        self.position = after
        if after == 0:
            self.entry = Decimal("0")

    def trigger(self, coi: int) -> None:
        """A Stop fires: it leaves the book and the Position closes."""
        del self.orders[coi]
        self.position = Decimal("0")
        self.entry = Decimal("0")

    def sent(self, kind: str) -> list[dict[str, Any]]:
        return [kw for k, kw in self.calls if k == kind]

    def resting(self, kind: str = "limit") -> list[dict[str, Any]]:
        """Orders on the book now, by type, in the order they went on."""
        return [row for row in self.orders.values() if row["order_type"] == kind]

    def execution(self) -> ChaseExecution:
        return ChaseExecution(
            enabled=True,
            get_market_by_index=lambda mi: self.meta if mi == MI else None,
            best_bid_ask=lambda mi: (self.bid, self.ask),
            is_book_synced=lambda mi: True,
            create_limit_order=self.create_limit_order,
            create_market_order=self.create_market_order,
            modify_order=self.modify_order,
            cancel_order=self.cancel_order,
            cancel_all_orders=MagicMock(),
            cached_account_payload=self.payload,
            get_account_summary=MagicMock(),
            kick_refresh=lambda: None,
            orders_hydrated=lambda: True,
            create_trigger_leg=self.create_trigger_leg,
            amend_trigger_leg=self.amend_trigger_leg,
        )


class FakeBook:
    def __init__(self, venue: FakeVenue) -> None:
        self.venue = venue
        self.coi = PLANNER_COI_BASE
        self.finished: list[PlannerRunner] = []
        self.published = 0

    def publish(self) -> None:
        self.published += 1

    def finish(self, job: PlannerRunner) -> None:
        self.finished.append(job)

    def alloc_coi(self) -> int:
        self.coi += 1
        return self.coi

    amend_budget = 1_000

    def take_amend(self, market_index: int, now_ms: int) -> bool:
        if self.amend_budget <= 0:
            return False
        self.amend_budget -= 1
        return True

    def execution(self) -> ChaseExecution:
        return self.venue.execution()
