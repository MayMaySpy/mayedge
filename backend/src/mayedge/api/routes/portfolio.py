from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from mayedge.config import settings
from mayedge.persist_portfolio import portfolio_buckets
from mayedge.portfolio import DAY_MS, OpenRefused, day_open, days, history
from mayedge.portfolio_venue import read_portfolio

router = APIRouter()


@router.get("/api/portfolio")
async def get_portfolio(open: int | None = None, detail: bool = True) -> dict[str, Any]:
    """The Portfolio now and since the Day open (docs/portfolio-rules.md N1–N8)."""
    if not settings.trading_enabled:
        raise HTTPException(400, "Account not configured")
    try:
        open_ms = day_open(open, int(time.time() * 1000))
    except OpenRefused as e:
        raise HTTPException(400, str(e)) from e
    try:
        result = await read_portfolio(open_ms, detail=detail)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Lighter answered {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "Lighter did not answer") from e
    return result.to_json()


_RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "all": None}


def _since(range_: str, now_ms: int) -> int:
    if range_ not in _RANGES:
        raise HTTPException(400, "range must be 1d, 7d, 30d, 90d, or all")
    span = _RANGES[range_]
    return 0 if span is None else now_ms - span * DAY_MS


@router.get("/api/portfolio/history")
async def get_portfolio_history(range: str = "7d") -> dict[str, Any]:
    """H4, H5: stored values per kind, hourly for 1d and 7d, daily beyond. No venue read."""
    since = _since(range, int(time.time() * 1000))
    resolution = "1h" if range in ("1d", "7d") else "1d"
    out = history(portfolio_buckets(resolution, "values", since), portfolio_buckets(resolution, "pnl", since))
    return {"range": range, "resolution": resolution, **out}


@router.get("/api/portfolio/days")
async def get_portfolio_days(range: str = "30d", tz: int = 0) -> dict[str, Any]:
    """H6: Day change per kind per local day. No venue read."""
    now = int(time.time() * 1000)
    if range == "1d":
        raise HTTPException(400, "range must be 7d, 30d, 90d, or all")
    since = _since(range, now)
    if not -14 * 60 <= tz <= 14 * 60:
        raise HTTPException(400, "tz is minutes from UTC, -840 to 840")
    rows = days(
        portfolio_buckets("1h", "pnl", since - DAY_MS),
        portfolio_buckets("1d", "pnl", since - DAY_MS),
        since_ms=since,
        now_ms=now,
        tz_min=tz,
    )
    return {"range": range, "tz": tz, "days": rows}
