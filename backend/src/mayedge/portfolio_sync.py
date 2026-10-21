"""Keep the venue's pnl buckets in the desk (docs/portfolio-rules.md H1–H3). Read only."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mayedge.persist_portfolio import (
    portfolio_backfilled,
    portfolio_note_backfilled,
    portfolio_oldest_ms,
    portfolio_put_buckets,
)
from mayedge.portfolio import DAY_MS, HOUR_MS, to_ms

logger = logging.getLogger(__name__)

BOOT_DELAY_S = 30
INTERVAL_S = 300
MODES = ("pnl", "values")
# resolution → (bucket, buckets per backfill window, backfill horizon, latest buckets per sync)
RESOLUTIONS: dict[str, tuple[int, int, int, int]] = {
    "1h": (HOUR_MS, 48, 90 * DAY_MS, 3),
    "1d": (DAY_MS, 30, 730 * DAY_MS, 2),
}

# (resolution, mode, start ms, end ms, buckets) → the venue's rows.
Fetch = Callable[[str, str, int, int, int], Awaitable[list[dict[str, Any]]]]

_task: asyncio.Task[None] | None = None
# The venue's answer for a window older than it keeps at that resolution (H2).
HORIZON_CODE = 22403


class HorizonReached(Exception):
    """The venue keeps nothing older at this resolution."""


def closed(rows: list[dict[str, Any]], step_ms: int) -> list[tuple[int, dict[str, Any]]]:
    """H1: only buckets on the hour or on UTC midnight. The partial one is stamped now."""
    out: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        ts = to_ms(row.get("timestamp"))
        if ts > 0 and ts % step_ms == 0:
            out.append((ts, row))
    return out


def _all_zero(rows: list[dict[str, Any]]) -> bool:
    """H2: every field zero in every bucket — before the account existed."""
    for row in rows:
        for key, value in row.items():
            if key != "timestamp" and isinstance(value, int | float) and value != 0:
                return False
    return True


async def _read(fetch: Fetch, resolution: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Both modes for one window; stores the closed buckets and returns every row read."""
    step, _window, _horizon, _latest = RESOLUTIONS[resolution]
    count = max(1, (end_ms - start_ms) // step + 1)
    seen: list[dict[str, Any]] = []
    for mode in MODES:
        rows = await fetch(resolution, mode, start_ms, end_ms, count)
        portfolio_put_buckets(resolution, mode, closed(rows, step))
        seen.extend(rows)
    return seen


async def _backfill(fetch: Fetch, resolution: str, now_ms: int) -> None:
    """H2: walk back from the oldest stored bucket until before the account, or the horizon."""
    step, window, horizon, _latest = RESOLUTIONS[resolution]
    floor = now_ms - horizon
    end = portfolio_oldest_ms(resolution) or (now_ms - now_ms % step)
    while True:
        start = max(floor, end - window * step)
        try:
            rows = await _read(fetch, resolution, start, end)
        except HorizonReached:
            logger.info(
                "portfolio %s backfill reached the venue's horizon at %s", resolution, start
            )
            portfolio_note_backfilled(resolution)
            return
        if (rows and _all_zero(rows)) or start <= floor:
            portfolio_note_backfilled(resolution)
            return
        if not rows:
            # The venue had nothing for a window inside the account's life: try again next sync.
            logger.info("portfolio %s backfill got an empty window at %s", resolution, start)
            return
        end = start


async def sync_once(fetch: Fetch, *, enabled: bool, now_ms: int | None = None) -> dict[str, Any]:
    """H3: the latest buckets every time; the backfill until it is done."""
    if not enabled:
        return {"started": False}
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    for resolution, (step, _window, _horizon, latest) in RESOLUTIONS.items():
        await _read(fetch, resolution, now - now % step - latest * step, now)
        if not portfolio_backfilled(resolution):
            await _backfill(fetch, resolution, now)
    return {"started": True}


async def _venue_fetch(
    resolution: str, mode: str, start_ms: int, end_ms: int, count: int
) -> list[dict[str, Any]]:
    import httpx

    from mayedge.config import settings
    from mayedge.lighter.budget import budget
    from mayedge.lighter.orders import order_service

    await budget.take("background", wait=True)
    params: dict[str, Any] = {
        "by": "index",
        "value": str(settings.lighter_account_index),
        "resolution": resolution,
        "start_timestamp": start_ms,
        "end_timestamp": end_ms,
        "count_back": count,
    }
    if mode == "values":
        params["ignore_transfers"] = "true"
    auth = await order_service.auth_token()
    async with httpx.AsyncClient(base_url=settings.base_url, timeout=20.0) as client:
        resp = await client.get(
            "/api/v1/pnl",
            params=params,
            headers={"authorization": auth, "Accept": "application/json"},
        )
        if resp.status_code == 400 and _code(resp) == HORIZON_CODE:
            raise HorizonReached(resolution)
        if resp.status_code >= 400:
            logger.warning(
                "portfolio pnl %s %s→%s answered %s: %s",
                resolution,
                start_ms,
                end_ms,
                resp.status_code,
                resp.text[:300],
            )
        resp.raise_for_status()
        body = resp.json()
    rows = body.get("pnl") if isinstance(body, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def _code(resp: Any) -> int | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, int) else None


async def _loop() -> None:
    from mayedge.config import settings

    if not settings.trading_enabled:
        return
    await asyncio.sleep(BOOT_DELAY_S)
    while True:
        try:
            await sync_once(_venue_fetch, enabled=settings.trading_enabled)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("portfolio sync failed")
        await asyncio.sleep(INTERVAL_S)


def start() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
