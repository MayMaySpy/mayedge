"""Read the Portfolio from the venue (docs/portfolio-rules.md N7). Read only.

Raw JSON, not SDK models: the live answer has fields the models lack and lacks
some they require (V6).
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from mayedge.config import settings
from mayedge.lighter.budget import budget
from mayedge.lighter.equity import MarginPart
from mayedge.portfolio import HOUR_MS, MarginRow, PortfolioNow, portfolio_now

REUSE_S = 30.0

_cache: dict[tuple[int, bool], tuple[float, PortfolioNow]] = {}


async def _get(
    client: httpx.AsyncClient, auth: str, path: str, params: dict[str, Any]
) -> dict[str, Any]:
    await budget.take("read", wait=True)
    resp = await client.get(
        path, params=params, headers={"authorization": auth, "Accept": "application/json"}
    )
    resp.raise_for_status()
    body = resp.json()
    return body if isinstance(body, dict) else {}


async def read_venue(open_ms: int, now_ms: int, *, detail: bool = True) -> dict[str, Any]:
    """The two pnl series from the open to now; with detail, the account and each pool it holds shares in."""
    from mayedge.lighter.orders import order_service

    account_index = settings.lighter_account_index
    if account_index is None:
        raise ValueError("Account not configured")
    auth = await order_service.auth_token()
    hours = max(1, (now_ms - open_ms) // HOUR_MS + 2)
    series = {
        "by": "index",
        "value": str(account_index),
        "resolution": "1h",
        "start_timestamp": open_ms - HOUR_MS,
        "end_timestamp": now_ms,
        "count_back": hours,
    }
    async with httpx.AsyncClient(base_url=settings.base_url, timeout=20.0) as client:
        pnl = await _get(client, auth, "/api/v1/pnl", series)
        values = await _get(client, auth, "/api/v1/pnl", {**series, "ignore_transfers": "true"})
        account: dict[str, Any] = {}
        pools: dict[int, dict[str, Any]] = {}
        if detail:
            found = await _get(
                client, auth, "/api/v1/account", {"by": "index", "value": str(account_index)}
            )
            account = (found.get("accounts") or [{}])[0]
        for share in account.get("shares") or []:
            index = int(share.get("public_pool_index") or 0)
            if index and index not in pools:
                body = await _get(
                    client, auth, "/api/v1/account", {"by": "index", "value": str(index)}
                )
                pools[index] = (body.get("accounts") or [{}])[0]
    return {
        "pnl": pnl.get("pnl") or [],
        "values": values.get("pnl") or [],
        "account": account,
        "pools": pools,
    }


async def read_portfolio(
    open_ms: int, *, now_ms: int | None = None, detail: bool = True
) -> PortfolioNow:
    """N7: one venue read per Day open every 30s. N8: without detail, only the two pnl series."""
    from mayedge.lighter.account import account_service

    now = time.monotonic()
    # A detailed answer also serves a plain one.
    hit = _cache.get((open_ms, True)) or (None if detail else _cache.get((open_ms, False)))
    if hit is not None and now - hit[0] < REUSE_S:
        return hit[1]
    stamp = now_ms if now_ms is not None else int(time.time() * 1000)
    raw = await read_venue(open_ms, stamp, detail=detail)
    lit = account_service._live_asset_meta().get("LIT", {}).get("index_price") or 0.0  # pyright: ignore[reportPrivateUsage]
    result = portfolio_now(
        now_ms=stamp,
        open_ms=open_ms,
        pnl_rows=raw["pnl"],
        value_rows=raw["values"],
        account=raw["account"],
        pool_accounts=raw["pools"],
        live_assets=list(account_service._summary.assets),  # pyright: ignore[reportPrivateUsage]
        lit_price=Decimal(str(lit)),
        upnl=_upnl(account_service._summary.unrealized_pnl),  # pyright: ignore[reportPrivateUsage]
        detail=detail,
        margin=_margin(account_service.margin_parts()) if detail else None,
        margin_free=Decimal(str(account_service.margin_free())) if detail else None,
    )
    _cache[(open_ms, detail)] = (now, result)
    for key in [k for k, (at, _r) in _cache.items() if now - at >= REUSE_S]:
        _cache.pop(key, None)
    return result


def clear_cache() -> None:
    _cache.clear()


def _upnl(raw: object) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except ArithmeticError:
        return None


def _margin(parts: list[MarginPart]) -> list[MarginRow]:
    return [
        MarginRow(
            symbol=p.symbol,
            cross=p.cross,
            qty=Decimal(str(p.qty)),
            price=Decimal(str(p.index)),
            ltv=Decimal(str(p.ltv)),
            value=Decimal(str(p.value)),
        )
        for p in parts
    ]
