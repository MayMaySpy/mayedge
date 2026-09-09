"""Lighter desk: gateway, orders, chase book, and WS broadcast wiring."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mayedge import feed_health
from mayedge.algos.chase import HISTORY_CAP
from mayedge.algos.chase.book import ChaseBook
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.twap.book import AdvancedTwapBook
from mayedge.algos.twap.plan import TWAP_COI_BASE, TWAP_COI_END
from mayedge.lighter.account import account_service
from mayedge.lighter.gateway import gateway
from mayedge.lighter.orders import order_service

logger = logging.getLogger(__name__)

_broadcast: Callable[[dict[str, Any]], None] | None = None


def _created_at(snap: dict[str, Any]) -> int:
    raw = snap.get("created_at")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _book_rows(payload: dict[str, object], key: str) -> list[dict[str, Any]]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _account_ws_live() -> bool:
    return feed_health.snapshot().get("account_ws") == "live"


def execution() -> ChaseExecution:
    return ChaseExecution(
        enabled=order_service.enabled,
        get_market_by_index=gateway.get_market_by_index,
        best_bid_ask=gateway.best_bid_ask,
        is_book_synced=gateway.is_book_synced,
        create_limit_order=order_service.create_limit_order,
        create_market_order=order_service.create_market_order,
        modify_order=order_service.modify_order,
        cancel_order=order_service.cancel_order,
        cancel_all_orders=order_service.cancel_all_orders,
        cached_account_payload=account_service.cached_account_payload,
        get_account_summary=order_service.get_account_summary,
        get_account_trades=order_service.get_account_trades,
        kick_refresh=order_service.kick_refresh,
        orders_hydrated=account_service.orders_hydrated,
        list_markets=gateway.list_markets,
        ensure_book=gateway.ensure_order_book,
        release_book=gateway.release_order_book,
        account_ws_live=_account_ws_live,
    )


def _publish_algo_book(_payload: dict[str, Any]) -> None:
    if _broadcast:
        _broadcast(algo_book())


chase_book = ChaseBook(
    execution=execution,
    broadcast=_publish_algo_book,
    coi_base=8_000_000_000,
    coi_end=9_000_000_000,
)
twap_book = AdvancedTwapBook(
    execution=execution,
    broadcast=_publish_algo_book,
    coi_base=TWAP_COI_BASE,
    coi_end=TWAP_COI_END,
)


def algo_book() -> dict[str, Any]:
    chase = chase_book.to_dict()
    twap = twap_book.to_dict()
    working = _book_rows(chase, "working") + _book_rows(twap, "working")
    working.sort(key=_created_at, reverse=True)
    history = _book_rows(chase, "history") + _book_rows(twap, "history")
    history.sort(key=_created_at, reverse=True)
    history = history[:HISTORY_CAP]
    return {
        "type": "algo",
        "id": "algos",
        "working": working,
        "history": history,
    }


async def stop_algo(algo_id: str | None = None) -> dict[str, Any]:
    await chase_book.stop(algo_id)
    await twap_book.stop(algo_id)
    return algo_book()


async def pause_algo(algo_id: str) -> dict[str, Any]:
    if chase_book.has(algo_id):
        await chase_book.pause(algo_id)
    elif twap_book.has(algo_id):
        await twap_book.pause(algo_id)
    else:
        raise ValueError(f"unknown algo_id {algo_id}")
    return algo_book()


async def unpause_algo(algo_id: str) -> dict[str, Any]:
    if chase_book.has(algo_id):
        await chase_book.unpause(algo_id)
    elif twap_book.has(algo_id):
        await twap_book.unpause(algo_id)
    else:
        raise ValueError(f"unknown algo_id {algo_id}")
    return algo_book()


def set_broadcast(fn: Callable[[dict[str, Any]], None] | None) -> None:
    global _broadcast
    _broadcast = fn
    if fn is not None:
        gateway.subscribe(_on_gateway)
    else:
        gateway.unsubscribe(_on_gateway)


def _on_gateway(msg: dict[str, Any]) -> None:
    if _broadcast:
        _broadcast(msg)
    chase_book.on_gateway(msg)
    twap_book.on_gateway(msg)


async def start() -> None:
    await gateway.start()
    await order_service.start()


async def stop() -> None:
    await chase_book.drain_for_shutdown()
    await twap_book.drain_for_shutdown()
    await chase_book.flush()
    await twap_book.flush()
    await order_service.stop()
    await gateway.stop()


async def restore() -> None:
    await chase_book.restore()
    await twap_book.restore()
    _publish_algo_book({})
