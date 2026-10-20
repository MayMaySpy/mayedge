from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from mayedge import db as store
from mayedge.api.deps import _market_index
from mayedge.api.token_icon import token_icon_response
from mayedge.lighter.gateway import gateway
from mayedge.persist_liq import liquidation_summary_since_ms

router = APIRouter()


@router.get("/api/liquidations")
async def get_liquidations(
    limit: int = 200,
    min_usd: float | None = None,
    market_index: int | None = None,
) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit), 1000))
    ring = gateway.recent_liquidations()
    if ring and min_usd is None and market_index is None:
        return ring[:cap]
    return store.list_liquidations(limit=limit, min_usd=min_usd, market_index=market_index)


@router.get("/api/liquidations/summary")
async def get_liquidation_summary(hours: int = 24) -> dict[str, Any]:
    try:
        since = liquidation_summary_since_ms(hours)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    store.fold_liquidations_if_due()
    return {
        "hours": hours,
        "since": since,
        "rows": store.summarize_liquidations(since_ms=since),
    }


@router.get("/api/markets")
async def list_markets() -> list[dict[str, Any]]:
    return [m.as_public_dict() for m in gateway.list_markets()]


@router.get("/api/markets/{symbol}")
async def get_market(symbol: str) -> dict[str, Any]:
    meta = gateway.get_market(symbol)
    if not meta:
        raise HTTPException(404, "Market not found")
    return meta.as_public_dict()


@router.get("/api/oi/{symbol}")
async def get_open_interest(
    symbol: str, resolution: str = "1m", count: int = 500
) -> list[dict[str, Any]]:
    meta = gateway.get_market(symbol)
    if not meta:
        raise HTTPException(404, "Market not found")
    if not meta.is_perp:
        return []
    n = min(max(int(count), 1), 3600)
    try:
        return store.list_open_interest(meta.market_index, resolution=resolution, count=n)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/funding/{symbol}/average")
async def get_funding_average(symbol: str) -> dict[str, Any]:
    meta = gateway.get_market(symbol)
    if not meta:
        raise HTTPException(404, "Market not found")
    if not meta.is_perp:
        return {"windows": [], "first_time": None}
    return store.funding_averages(meta.market_index)


@router.get("/api/funding/{symbol}")
async def get_funding_history(
    symbol: str, resolution: str = "1h", count: int = 500
) -> list[dict[str, Any]]:
    meta = gateway.get_market(symbol)
    if not meta:
        raise HTTPException(404, "Market not found")
    if not meta.is_perp:
        return []
    n = min(max(int(count), 1), 3600)
    try:
        return store.list_funding(meta.market_index, resolution=resolution, count=n)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/candles/{symbol}")
async def get_candles(symbol: str, resolution: str = "1m", count: int = 500) -> list[dict]:
    idx = _market_index(symbol)
    cap = 3600 if resolution == "1s" else 500
    n = min(max(int(count), 1), cap)
    candles = await gateway.get_candles(idx, resolution, n)
    return [
        {
            "time": c.time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]


@router.post("/api/markets/{symbol}/activate")
async def activate_market(symbol: str) -> dict[str, str]:
    idx = _market_index(symbol)
    await gateway.set_active_market(idx)
    return {"status": "ok", "market_index": str(idx)}


@router.get("/api/token-icon/{slug}")
async def token_icon(slug: str) -> Response:
    return await token_icon_response(slug)
