"""Journal sync pages until it sees a stored fill, and does nothing when trading is off."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

from mayedge import db as store
from mayedge.config import settings
from mayedge.journal_sync import sync_once
from mayedge.persist_journal import (
    journal_backfilled,
    journal_insert_fills,
    journal_load_fills,
    journal_note_backfilled,
    journal_oldest_ts,
)


def _fill(trade_id: str, ts: int) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "market_index": 1,
        "symbol": "ETH",
        "side": "buy",
        "is_maker": False,
        "price": "100",
        "size": "1",
        "usd": "100",
        "fee": "0",
        "pnl": "0",
        "kind": "trade",
        "ts": ts,
    }


class JournalSyncTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "journal.db")
        self.addCleanup(self._restore)
        self.takes = 0

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old

    async def _take(self) -> None:
        self.takes += 1

    async def test_paging_stops_at_a_known_trade_and_a_replay_inserts_nothing(self) -> None:
        journal_insert_fills([_fill("1", 10)])
        journal_note_backfilled("trades")
        calls: list[tuple[str, str | None]] = []

        async def trades(cursor: str | None) -> dict[str, Any]:
            calls.append(("t", cursor))
            if cursor is None:
                return {"rows": [_fill("3", 30), _fill("2", 20)], "next": "p2"}
            if cursor == "p2":
                return {"rows": [_fill("1", 10)], "next": "p3"}
            raise AssertionError(f"paged past the known trade at {cursor}")

        async def funding(cursor: str | None) -> dict[str, Any]:
            calls.append(("f", cursor))
            return {"rows": [{"market_index": 1, "ts": 15, "amount": "1.5"}], "next": None}

        first = await sync_once(trades, funding, self._take, enabled=True)
        self.assertTrue(first["started"])
        self.assertEqual([call for call in calls if call[0] == "t"], [("t", None), ("t", "p2")])
        self.assertEqual(self.takes, 3)
        stored = {row["trade_id"] for row in journal_load_fills()}
        self.assertEqual(stored, {"1", "2", "3"})
        self.assertIsNone(journal_oldest_ts())

        calls.clear()
        self.takes = 0
        await sync_once(trades, funding, self._take, enabled=True)
        self.assertEqual(calls, [("t", None), ("f", None)])
        self.assertEqual(self.takes, 2)
        self.assertEqual({row["trade_id"] for row in journal_load_fills()}, {"1", "2", "3"})

    async def test_an_interrupted_backfill_walks_past_known_fills_until_it_reaches_the_end(self) -> None:
        # The first walk stored the newest page and then stopped (budget, network).
        journal_insert_fills([_fill("3", 30)])
        pages = {
            None: {"rows": [_fill("4", 40), _fill("3", 30)], "next": "p2"},
            "p2": {"rows": [_fill("2", 20)], "next": "p3"},
            "p3": {"rows": [_fill("1", 10)], "next": None},
        }

        async def trades(cursor: str | None) -> dict[str, Any]:
            return pages[cursor]

        async def funding(cursor: str | None) -> dict[str, Any]:
            return {"rows": [], "next": None}

        self.assertFalse(journal_backfilled("trades"))
        await sync_once(trades, funding, self._take, enabled=True)
        self.assertEqual({row["trade_id"] for row in journal_load_fills()}, {"1", "2", "3", "4"})
        self.assertTrue(journal_backfilled("trades"))
        self.assertTrue(journal_backfilled("funding"))
        self.assertEqual(journal_oldest_ts(), 10)

    async def test_a_full_backfill_records_the_oldest_timestamp(self) -> None:
        async def trades(cursor: str | None) -> dict[str, Any]:
            return {"rows": [_fill("9", 40), _fill("8", 10)], "next": None}

        async def funding(cursor: str | None) -> dict[str, Any]:
            return {"rows": [], "next": None}

        await sync_once(trades, funding, self._take, enabled=True)
        self.assertEqual(journal_oldest_ts(), 10)

    async def test_nothing_runs_when_trading_is_off(self) -> None:
        async def fetch(cursor: str | None) -> dict[str, Any]:
            raise AssertionError("fetched while trading is off")

        result = await sync_once(fetch, fetch, self._take, enabled=False)
        self.assertFalse(result["started"])
        self.assertEqual(self.takes, 0)
        self.assertEqual(journal_load_fills(), [])
