"""Emergency stop: halt algos, cancel all orders, optionally flatten positions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from mayedge.numbers import fmt_decimal, parse_decimal

logger = logging.getLogger(__name__)


class AlgoKill(Protocol):
    async def stop(self) -> None: ...


class OrdersKill(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def cancel_all_orders(self, market_index: int | None) -> Any: ...
    async def create_market_order(
        self,
        market_index: int,
        side: str,
        size: str,
        slippage: float,
        reduce_only: bool,
    ) -> Any: ...

    def kick_refresh(self) -> None: ...


class AccountSummaryKill(Protocol):
    positions: list[Any]


@dataclass(frozen=True)
class KillResult:
    status: str
    cancel_ok: bool
    cancel_error: str | None
    flatten: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cancel_ok": self.cancel_ok,
            "cancel_error": self.cancel_error,
            "flatten": self.flatten,
        }


async def kill(
    *,
    flatten: bool,
    algos: AlgoKill,
    orders: OrdersKill,
    get_account_summary: Any,
) -> KillResult:
    await algos.stop()

    cancel_ok = True
    cancel_error: str | None = None
    flatten_legs: list[dict[str, Any]] = []

    if orders.enabled:
        try:
            await orders.cancel_all_orders(None)
        except Exception as e:
            cancel_ok = False
            cancel_error = str(e)
            logger.exception("kill cancel_all failed")

    if flatten and orders.enabled:
        try:
            summary = await get_account_summary()
            for pos in summary.positions:
                try:
                    size_raw = parse_decimal(pos.size)
                except ValueError:
                    flatten_legs.append({
                        "market_index": pos.market_index,
                        "symbol": pos.symbol,
                        "ok": False,
                        "error": f"invalid size {pos.size!r}",
                    })
                    continue
                if size_raw == 0:
                    continue
                size_dec = abs(size_raw)
                side = "sell" if size_raw > 0 else "buy"
                leg: dict[str, Any] = {
                    "market_index": pos.market_index,
                    "symbol": pos.symbol,
                    "ok": False,
                    "error": None,
                }
                try:
                    await orders.create_market_order(
                        pos.market_index,
                        side,
                        fmt_decimal(size_dec) or "0",
                        0.01,
                        True,
                    )
                    leg["ok"] = True
                except Exception as e:
                    leg["error"] = str(e)
                    logger.exception(
                        "kill flatten leg failed market=%s",
                        pos.market_index,
                    )
                flatten_legs.append(leg)
        except Exception as e:
            logger.exception("kill flatten failed")
            flatten_legs.append({"ok": False, "error": str(e)})

    flatten_ok = all(leg.get("ok") for leg in flatten_legs) if flatten_legs else True
    killed = cancel_ok and (not flatten or flatten_ok)
    if orders.enabled:
        orders.kick_refresh()

    return KillResult(
        status="killed" if killed else "partial",
        cancel_ok=cancel_ok,
        cancel_error=cancel_error,
        flatten=flatten_legs,
    )
