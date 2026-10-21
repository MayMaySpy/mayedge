"""Page the venue into the journal. Rules: docs/journal-rules.md."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mayedge.lighter.budget import BudgetRefused
from mayedge.persist_journal import (
    journal_backfilled,
    journal_insert_fills,
    journal_insert_funding,
    journal_known_funding,
    journal_known_trade_ids,
    journal_last_synced_at,
    journal_note_backfilled,
    journal_note_oldest,
    journal_note_synced,
)

logger = logging.getLogger(__name__)

PAGE = 100
BOOT_DELAY_S = 30
INTERVAL_S = 300
FILL_DELAY_S = 10

Page = Callable[[str | None], Awaitable[dict[str, Any]]]
Take = Callable[[], Awaitable[None]]

_task: asyncio.Task[None] | None = None
_wake = asyncio.Event()
_fill_at = 0.0


def note_fill() -> None:
    """The account feed reported a fill. Sync once the burst has been quiet for 10s."""
    global _fill_at
    _fill_at = time.monotonic()
    _wake.set()


def start() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def sync_once(
    fetch_trades: Page,
    fetch_funding: Page,
    take: Take,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """One pass. `take` runs once per page, before the fetch, and may wait."""
    if not enabled:
        return {"started": False, "last_synced_at": journal_last_synced_at()}
    trade_end, trade_oldest = await _page(
        fetch_trades,
        take,
        kind="trades",
        known=lambda rows: journal_known_trade_ids([str(row["trade_id"]) for row in rows]),
        insert=journal_insert_fills,
    )
    funding_end, _ = await _page(
        fetch_funding,
        take,
        kind="funding",
        known=_known_funding,
        insert=journal_insert_funding,
    )
    if trade_end:
        journal_note_backfilled("trades")
    if funding_end:
        journal_note_backfilled("funding")
    # Oldest is how far the fill history reached. Funding is not a Position's open.
    if trade_end and trade_oldest is not None:
        journal_note_oldest(trade_oldest)
    journal_note_synced()
    return {"started": True, "last_synced_at": journal_last_synced_at()}


def _known_funding(rows: list[dict[str, Any]]) -> set[str]:
    keys = [(int(row["market_index"]), int(row["ts"])) for row in rows]
    return {f"{market}:{ts}" for market, ts in journal_known_funding(keys)}


async def _page(
    fetch: Page,
    take: Take,
    *,
    kind: str,
    known: Callable[[list[dict[str, Any]]], set[str]],
    insert: Callable[[list[dict[str, Any]]], None],
) -> tuple[bool, int | None]:
    """Returns whether the venue had no further page, and the oldest ts seen.

    Until one walk has reached the venue's oldest page, a known row does not stop
    the walk: an interrupted first backfill would otherwise leave a hole for good.
    """
    complete = journal_backfilled(kind)
    cursor: str | None = None
    oldest: int | None = None
    while True:
        try:
            await take()
        except BudgetRefused:
            logger.info("journal %s sync yielded to the rate budget", kind)
            return False, None
        page = await fetch(cursor)
        rows = list(page.get("rows") or [])
        hit = known(rows)
        insert(rows)
        for row in rows:
            ts = int(row["ts"])
            oldest = ts if oldest is None else min(oldest, ts)
        nxt = page.get("next")
        cursor = None if nxt in (None, "") else str(nxt)
        if not rows or (hit and complete) or cursor is None:
            # A known id stops the walk. An empty cursor means the venue has nothing older.
            return cursor is None, oldest
        await asyncio.sleep(0)


async def _loop() -> None:
    from mayedge.config import settings

    if not settings.trading_enabled:
        return
    try:
        await asyncio.sleep(BOOT_DELAY_S)
        while True:
            try:
                await run_sync()
            except Exception:
                logger.exception("journal sync failed")
            try:
                from mayedge.api.routes.journal import warm as warm_journal

                await warm_journal()
            except Exception:
                logger.exception("journal warm failed")
            _wake.clear()
            try:
                await asyncio.wait_for(_wake.wait(), timeout=INTERVAL_S)
            except TimeoutError:
                continue
            while time.monotonic() - _fill_at < FILL_DELAY_S:
                await asyncio.sleep(FILL_DELAY_S)
    except asyncio.CancelledError:
        raise


async def run_sync() -> dict[str, Any]:
    from mayedge.config import settings
    from mayedge.lighter.account import account_service
    from mayedge.lighter.budget import budget

    async def take() -> None:
        await budget.take("background", wait=True)

    async def trades(cursor: str | None) -> dict[str, Any]:
        page = await account_service.fetch_account_trades(
            cursor=cursor, limit=PAGE, budgeted=False
        )
        return {"rows": [_fill_row(row) for row in page.get("trades") or []], "next": page.get("next_cursor")}

    async def funding(cursor: str | None) -> dict[str, Any]:
        page = await account_service.fetch_account_funding(
            cursor=cursor, limit=PAGE, budgeted=False
        )
        return {
            "rows": [_funding_row(row) for row in page.get("fundings") or []],
            "next": page.get("next_cursor"),
        }

    return await sync_once(trades, funding, take, enabled=settings.trading_enabled)


def _fill_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": row["trade_id"],
        "market_index": row["market_index"],
        "symbol": row["symbol"],
        "side": row["side"],
        "is_maker": row["is_maker"],
        "price": row["price"],
        "size": row["size"],
        "usd": row.get("usd_amount", row.get("usd", "0")),
        "fee": row["fee"],
        "pnl": row["pnl"],
        "kind": row.get("type", row.get("kind", "trade")),
        "ts": row.get("timestamp", row.get("ts", 0)),
    }


def _funding_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_index": row["market_index"],
        "ts": row.get("timestamp", row.get("ts", 0)),
        "amount": row.get("change", row.get("amount", "0")),
    }
