from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mayedge.api.deps import _account_history, _order_service
from mayedge.config import settings
from mayedge.lighter.account import account_service
from mayedge.lighter.budget import budget

router = APIRouter()


@router.get("/api/account")
async def get_account() -> dict[str, Any]:
    cached = account_service.cached_account_payload()
    if cached:
        out = dict(cached)
        out.pop("type", None)
        out.pop("venue", None)
        return out
    token = budget.enter_lane("read")
    try:
        summary = await _order_service().get_account_summary()
    finally:
        budget.leave_lane(token)
    return summary.to_public_dict()


@router.get("/api/account/trades")
async def get_account_trades(
    market_index: int | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not settings.lighter_account_index:
        raise HTTPException(400, "Account not configured")
    return await _account_history(
        lambda: _order_service().get_account_trades(
            market_id=market_index,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get("/api/account/funding")
async def get_account_funding(
    market_index: int | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not settings.lighter_account_index:
        raise HTTPException(400, "Account not configured")
    return await _account_history(
        lambda: _order_service().get_account_funding(
            market_id=market_index,
            cursor=cursor,
            limit=limit,
        )
    )
