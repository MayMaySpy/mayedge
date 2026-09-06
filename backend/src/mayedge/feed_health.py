"""Shared Lighter feed health for market + account websockets."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

FeedStatus = Literal["live", "reconnecting", "stale", "down"]

_market_ws: FeedStatus = "down"
_account_ws: FeedStatus = "down"
_market_last_msg_at: int = 0
_account_last_msg_at: int = 0
_trade_subs: int = 0
_trade_subs_target: int = 0
_emitter: Callable[[dict[str, Any]], None] | None = None


def set_emitter(fn: Callable[[dict[str, Any]], None] | None) -> None:
    global _emitter
    _emitter = fn


def _now_ms() -> int:
    return int(time.time() * 1000)


def set_market_ws(
    status: FeedStatus,
    *,
    last_msg_at: int | None = None,
    trade_subs: int | None = None,
    trade_subs_target: int | None = None,
    broadcast: bool = True,
) -> None:
    global _market_ws, _market_last_msg_at, _trade_subs, _trade_subs_target
    _market_ws = status
    if last_msg_at is not None:
        _market_last_msg_at = last_msg_at
    if trade_subs is not None:
        _trade_subs = trade_subs
    if trade_subs_target is not None:
        _trade_subs_target = trade_subs_target
    if broadcast:
        _emit()


def touch_market_msg() -> None:
    global _market_last_msg_at, _market_ws
    _market_last_msg_at = _now_ms()
    if _market_ws != "live":
        _market_ws = "live"
        _emit()


def set_account_ws(
    status: FeedStatus, *, last_msg_at: int | None = None, broadcast: bool = True
) -> None:
    global _account_ws, _account_last_msg_at
    _account_ws = status
    if last_msg_at is not None:
        _account_last_msg_at = last_msg_at
    if broadcast:
        _emit()


def touch_account_msg() -> None:
    global _account_last_msg_at, _account_ws
    _account_last_msg_at = _now_ms()
    if _account_ws != "live":
        _account_ws = "live"
        _emit()


def snapshot() -> dict[str, Any]:
    return {
        "type": "feed_health",
        "market_ws": _market_ws,
        "account_ws": _account_ws,
        "last_msg_at": _market_last_msg_at,
        "account_last_msg_at": _account_last_msg_at,
        "trade_subs": _trade_subs,
        "trade_subs_target": _trade_subs_target,
        "ts": _now_ms(),
    }


def _emit() -> None:
    if _emitter is None:
        return
    try:
        _emitter(snapshot())
    except Exception:
        pass
