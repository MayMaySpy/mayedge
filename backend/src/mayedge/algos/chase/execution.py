from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ChaseExecution:
    """Port chase uses instead of lighter singletons."""

    enabled: bool
    get_market_by_index: Callable[[int], Any | None]
    best_bid_ask: Callable[[int], tuple[str | None, str | None]]
    is_book_synced: Callable[[int], bool]
    create_limit_order: Callable[..., Any]
    create_market_order: Callable[..., Any]
    modify_order: Callable[..., Any]
    cancel_order: Callable[..., Any]
    cancel_all_orders: Callable[..., Any]
    cached_account_payload: Callable[[], dict[str, Any] | None]
    get_account_summary: Callable[[], Any]
    kick_refresh: Callable[[], None]
    orders_hydrated: Callable[[], bool]
    list_markets: Callable[[], list[Any]] | None = None
    ensure_book: Callable[..., Any] | None = None
    release_book: Callable[[int], None] | None = None
    account_ws_live: Callable[[], bool] | None = None
    get_account_trades: Callable[..., Any] | None = None
