"""Deterministic fakes for chase iceberg runner tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from mayedge.algos.chase import ChaseBook, ChaseIcebergParams
from mayedge.algos.chase.job import (
    ChaseIcebergRunner,
    ChaseState,
    ChaseStatus,
)
from mayedge.lighter.models import MarketMeta
from mayedge.algos.chase.execution import ChaseExecution


@dataclass
class FakeClock:
    now_ms: int = 1_000_000

    def advance(self, ms: int) -> None:
        self.now_ms += ms

    def __call__(self) -> int:
        return self.now_ms


@dataclass
class FakeGateway:
    market: MarketMeta | None = None
    bid: str | None = "100"
    ask: str | None = "100.10"
    broadcasts: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.market is None:
            self.market = MarketMeta(
                market_index=1,
                symbol="ETH",
                price_decimals=2,
                size_decimals=1,
                min_base_amount=0.1,
                min_quote_amount=0.0,
            )

    def get_market_by_index(self, market_index: int) -> MarketMeta | None:
        extra = getattr(self, "markets", None)
        if extra and market_index in extra:
            return extra[market_index]
        if self.market is None or self.market.market_index != market_index:
            return None
        return self.market

    def list_markets(self) -> list[MarketMeta]:
        extra = getattr(self, "markets", None)
        if extra:
            return list(extra.values())
        return [self.market] if self.market else []

    def add_spot_pair(self, *, spot_index: int = 2) -> MarketMeta:
        if self.market is None:
            raise RuntimeError("no perp")
        self.market.market_type = "perp"
        spot = MarketMeta(
            market_index=spot_index,
            symbol=self.market.symbol,
            price_decimals=self.market.price_decimals,
            size_decimals=self.market.size_decimals,
            min_base_amount=self.market.min_base_amount,
            min_quote_amount=self.market.min_quote_amount,
            market_type="spot",
        )
        self.markets = {self.market.market_index: self.market, spot_index: spot}
        self.spot_index = spot_index
        self.spot_bid = self.bid
        self.spot_ask = self.ask
        return spot

    def best_bid_ask(self, market_index: int) -> tuple[str | None, str | None]:
        if getattr(self, "spot_index", None) == market_index:
            return getattr(self, "spot_bid", self.bid), getattr(self, "spot_ask", self.ask)
        if self.market is None or self.market.market_index != market_index:
            return None, None
        return self.bid, self.ask

    def is_book_synced(self, market_index: int) -> bool:
        if getattr(self, "spot_index", None) == market_index:
            return self.spot_bid is not None and self.spot_ask is not None
        if self.market is None:
            return True
        if self.market.market_index != market_index:
            return False
        return self.bid is not None and self.ask is not None

    def subscribe(self, callback: Any) -> None:
        return None

    def broadcast(self, message: dict[str, Any]) -> None:
        self.broadcasts.append(message)

    def set_book(self, bid: str | None, ask: str | None) -> None:
        self.bid = bid
        self.ask = ask
        if getattr(self, "spot_index", None) is not None:
            self.spot_bid = bid
            self.spot_ask = ask


class FakeOrderService:
    """In-memory venue children for chase runner tests."""

    def __init__(self) -> None:
        self.enabled = True
        self.open_orders: list[dict[str, Any]] = []
        self.creates: list[dict[str, Any]] = []
        self.modifies: list[dict[str, Any]] = []
        self.modify_attempts: list[dict[str, Any]] = []
        self.cancels: list[tuple[int, int]] = []
        self._next_order_index = 100
        self.create_error: BaseException | None = None
        self.modify_error: BaseException | None = None
        self.cancel_error: BaseException | None = None
        self.cancel_error_once: BaseException | None = None
        self.summary_orders_override: list[dict[str, Any]] | None = None
        self.summary_calls = 0
        self._summary_sequence: list[list[dict[str, Any]] | None] = []
        self.orders_hydrated = True
        self.account_ws_live_flag = True
        self.trades_response: list[dict[str, Any]] = []
        self.trades_pages: list[list[dict[str, Any]]] | None = None
        self.trades_error: BaseException | None = None
        self.trades_calls = 0
        self.cached_orders_override: list[dict[str, Any]] | None = None
        self.cancel_keeps_open = False

    def cached_account_payload(self) -> dict[str, Any] | None:
        if self.cached_orders_override is not None:
            orders = self.cached_orders_override
        else:
            orders = self.open_orders
        return {"open_orders": list(orders), "type": "account"}

    def set_summary_sequence(self, *batches: list[dict[str, Any]]) -> None:
        self._summary_sequence = list(batches)

    async def get_account_trades(self, **kwargs: Any) -> dict[str, Any]:
        self.trades_calls += 1
        if self.trades_error is not None:
            raise self.trades_error
        if self.trades_pages is not None:
            raw_cursor = kwargs.get("cursor")
            page_idx = int(raw_cursor) if raw_cursor else 0
            if page_idx >= len(self.trades_pages):
                return {"trades": [], "next_cursor": None}
            trades = self.trades_pages[page_idx]
            next_cursor = str(page_idx + 1) if page_idx + 1 < len(self.trades_pages) else None
            return {"trades": list(trades), "next_cursor": next_cursor}
        return {"trades": list(self.trades_response), "next_cursor": None}

    async def get_account_summary(self) -> Any:
        self.summary_calls += 1
        if self._summary_sequence:
            orders = self._summary_sequence.pop(0)
        elif self.summary_orders_override is not None:
            orders = self.summary_orders_override
        else:
            orders = list(self.open_orders)
        # Runner only reads .open_orders; dict rows work with _chase_order_keys.
        return SimpleNamespace(open_orders=orders)

    async def create_limit_order(
        self,
        market_index: int,
        side: str,
        size: str,
        price: str,
        time_in_force: str = "gtt",
        reduce_only: bool = False,
        client_order_index: int | None = None,
    ) -> dict[str, Any]:
        if self.create_error is not None:
            raise self.create_error
        coi = int(client_order_index or 0)
        idx = self._next_order_index
        self._next_order_index += 1
        row = {
            "market_index": market_index,
            "order_index": idx,
            "client_order_index": coi,
            "side": side,
            "price": price,
            "initial": size,
            "remaining": size,
            "filled": "0",
            "size": size,
        }
        self.open_orders.append(row)
        self.creates.append(
            {
                "market_index": market_index,
                "side": side,
                "size": size,
                "price": price,
                "time_in_force": time_in_force,
                "reduce_only": reduce_only,
                "client_order_index": coi,
                "order_index": idx,
            }
        )
        return {"tx_hash": f"tx-{idx}", "client_order_index": coi}

    async def modify_order(
        self,
        market_index: int,
        order_index: int,
        price: str,
        *,
        size: str | None = None,
    ) -> dict[str, Any]:
        attempt = {
            "market_index": market_index,
            "order_index": order_index,
            "price": price,
            "size": size,
        }
        self.modify_attempts.append(attempt)
        if self.modify_error is not None:
            raise self.modify_error
        row = None
        for o in self.open_orders:
            if int(o["market_index"]) == market_index and (
                int(o["order_index"]) == order_index
                or int(o.get("client_order_index") or 0) == order_index
            ):
                row = o
                break
        if row is None:
            raise ValueError("order not found")
        row["price"] = price
        if size is not None:
            row["remaining"] = size
            row["size"] = size
            row["initial"] = size
        self.modifies.append(
            {
                "market_index": market_index,
                "order_index": order_index,
                "price": price,
                "size": size,
            }
        )
        return {"tx_hash": f"tx-mod-{order_index}"}

    async def cancel_order(self, market_index: int, order_index: int) -> dict[str, Any]:
        if self.cancel_error_once is not None:
            err, self.cancel_error_once = self.cancel_error_once, None
            raise err
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancels.append((market_index, order_index))
        if not self.cancel_keeps_open:
            self.open_orders = [
                o
                for o in self.open_orders
                if not (
                    int(o["market_index"]) == market_index and int(o["order_index"]) == order_index
                )
            ]
        return {"ok": True}

    def find_by_coi(self, coi: int) -> dict[str, Any] | None:
        for o in self.open_orders:
            if int(o.get("client_order_index") or 0) == coi:
                return o
        return None

    def set_remaining(self, coi: int, remaining: str, filled: str | None = None) -> None:
        row = self.find_by_coi(coi)
        if row is None:
            raise KeyError(coi)
        row["remaining"] = remaining
        if filled is not None:
            row["filled"] = filled
        else:
            initial = Decimal(str(row.get("initial") or row.get("size") or "0"))
            row["filled"] = str(initial - Decimal(remaining))

    def remove_by_coi(self, coi: int) -> None:
        self.open_orders = [
            o for o in self.open_orders if int(o.get("client_order_index") or 0) != coi
        ]


def make_execution(gateway: FakeGateway, orders: FakeOrderService) -> ChaseExecution:
    async def _cancel_all(_market_index: int | None) -> dict[str, Any]:
        return {"ok": True}

    async def _market_order(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"ok": True}

    async def _ensure_book(_mi: int) -> bool:
        return True

    return ChaseExecution(
        enabled=orders.enabled,
        get_market_by_index=gateway.get_market_by_index,
        best_bid_ask=gateway.best_bid_ask,
        is_book_synced=gateway.is_book_synced,
        create_limit_order=orders.create_limit_order,
        create_market_order=_market_order,
        modify_order=orders.modify_order,
        cancel_order=orders.cancel_order,
        cancel_all_orders=_cancel_all,
        cached_account_payload=orders.cached_account_payload,
        get_account_summary=orders.get_account_summary,
        get_account_trades=orders.get_account_trades,
        kick_refresh=lambda: None,
        orders_hydrated=lambda: bool(getattr(orders, "orders_hydrated", True)),
        account_ws_live=lambda: bool(getattr(orders, "account_ws_live_flag", True)),
        list_markets=gateway.list_markets,
        ensure_book=_ensure_book,
        release_book=lambda _mi: None,
    )


def make_test_book(
    gateway: FakeGateway,
    orders: FakeOrderService,
    *,
    broadcasts: list[dict[str, Any]] | None = None,
) -> ChaseBook:
    msgs = broadcasts if broadcasts is not None else gateway.broadcasts

    def _broadcast(payload: dict[str, Any]) -> None:
        msgs.append(payload)

    exec_holder = {"gateway": gateway, "orders": orders}

    return ChaseBook(
        execution=lambda: make_execution(exec_holder["gateway"], exec_holder["orders"]),
        broadcast=_broadcast,
    )


def buy_params(**kw: object) -> ChaseIcebergParams:
    base: dict[str, object] = dict(
        side="buy",
        qty=Decimal("10"),
        display_qty=Decimal("1"),
        offset_bps=Decimal("4"),
        price_floor=Decimal("90"),
        price_ceiling=Decimal("100"),
    )
    base.update(kw)
    return ChaseIcebergParams(**base)  # type: ignore[arg-type]


def sell_params(**kw: object) -> ChaseIcebergParams:
    return buy_params(side="sell", **kw)


@dataclass
class BootedJob:
    book: ChaseBook
    job: ChaseIcebergRunner
    clock: FakeClock
    gateway: FakeGateway
    orders: FakeOrderService
    algo_id: str


@contextmanager
def isolated_db() -> Iterator[None]:
    """Keep pytest off the live sqlite blotter.

    ChaseBook.alloc_* / publish / finish upsert through mayedge.db. These
    runner tests don't assert on sqlite; they must not write CH-* jobs into
    ./data/mayedge.db (Settings.db_path is a pydantic field and is awkward
    to patch).
    """
    with (
        patch("mayedge.db.save_counters"),
        patch("mayedge.db.upsert_run"),
        patch("mayedge.algos.chase.book.store.save_counters"),
        patch("mayedge.algos.chase.book.store.upsert_run"),
        patch("mayedge.algos.chase.book.store.load_history", return_value=[]),
        patch("mayedge.algos.chase.book.store.load_active_runs", return_value=[]),
        patch(
            "mayedge.algos.chase.book.store.load_counters", return_value={"id_seq": 0, "coi_seq": 0}
        ),
    ):
        yield


@contextmanager
def patch_chase(
    clock: FakeClock,
    gateway: FakeGateway,
    orders: FakeOrderService,
) -> Iterator[None]:
    with (
        isolated_db(),
        patch("mayedge.algos.chase.util.now_ms", clock),
    ):
        yield


def boot_job(
    *,
    params: ChaseIcebergParams | None = None,
    market_index: int = 1,
    algo_id: str = "CH-0001",
    reduce_only: bool = False,
    bid: str | None = "100",
    ask: str | None = "100.10",
    clock: FakeClock | None = None,
    gateway: FakeGateway | None = None,
    orders: FakeOrderService | None = None,
) -> BootedJob:
    """Fresh book+job in RUNNING state without starting the background loop."""
    clock = clock or FakeClock()
    gateway = gateway or FakeGateway()
    gateway.set_book(bid, ask)
    if gateway.market is not None:
        gateway.market.market_index = market_index
    orders = orders or FakeOrderService()
    book = make_test_book(gateway, orders)
    job = ChaseIcebergRunner(book)
    p = params or buy_params()
    job._state = ChaseState(
        status=ChaseStatus.RUNNING,
        params=p,
        market_index=market_index,
        symbol=gateway.market.symbol if gateway.market else "ETH",
        reduce_only=reduce_only,
        remaining=p.qty,
        algo_id=algo_id,
        created_at=clock.now_ms,
    )
    book._jobs[algo_id] = job
    return BootedJob(
        book=book,
        job=job,
        clock=clock,
        gateway=gateway,
        orders=orders,
        algo_id=algo_id,
    )


def trade_print(
    *,
    market_index: int,
    size: str,
    price: str,
    trade_id: int,
    bid_client_id: int = 0,
    ask_client_id: int = 0,
    bid_id: int = 0,
    ask_id: int = 0,
) -> dict[str, Any]:
    return {
        "market_index": market_index,
        "size": size,
        "price": price,
        "trade_id": trade_id,
        "bid_client_id": bid_client_id,
        "ask_client_id": ask_client_id,
        "bid_id": bid_id,
        "ask_id": ask_id,
    }
