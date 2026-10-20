from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from mayedge.config import settings
from mayedge.portfolio import OpenRefused, day_open
from mayedge.portfolio_venue import read_portfolio

router = APIRouter()


@router.get("/api/portfolio")
async def get_portfolio(open: int | None = None) -> dict[str, Any]:
    """The Portfolio now and since the Day open (docs/portfolio-rules.md N1–N7)."""
    if not settings.trading_enabled:
        raise HTTPException(400, "Account not configured")
    try:
        open_ms = day_open(open, int(time.time() * 1000))
    except OpenRefused as e:
        raise HTTPException(400, str(e)) from e
    try:
        result = await read_portfolio(open_ms)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Lighter answered {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "Lighter did not answer") from e
    return result.to_json()
