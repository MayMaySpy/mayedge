"""The journal routes rebuild stored fills and do not talk to the venue on a read."""

from __future__ import annotations

import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge import db as store
from mayedge.api.app import create_app
from mayedge.api.routes import journal as journal_routes
from mayedge.config import settings
from mayedge.journal_build import imports_gateway
from mayedge.lighter.account import account_service
from mayedge.lighter.models import AccountSummary, Position
from mayedge.persist_journal import (
    journal_generation,
    journal_insert_fills,
    journal_insert_funding,
    journal_put_note,
)
from mayedge.tone_compute import call as real_call
from mayedge.tone_compute import close as close_pool

try:
    from test_loop_free import assert_loop_free
except ImportError:  # `python -m unittest tests.test_journal_api`
    from tests.test_loop_free import assert_loop_free


def _hold_the_gil(_db_path: str, _upnl: dict[int, Decimal]) -> list[object]:
    """80 ms of CPU. Sleep would release the GIL and hide a loop stall."""
    end = time.perf_counter() + 0.08
    n = 0
    while time.perf_counter() < end:
        n += 1
    return []


def _fill(trade_id: str, side: str, ts: int, pnl: str = "0") -> dict[str, object]:
    return {
        "trade_id": trade_id,
        "market_index": 1,
        "symbol": "ETH",
        "side": side,
        "is_maker": True,
        "price": "110" if side == "sell" else "100",
        "size": "2",
        "usd": "200",
        "fee": "1",
        "pnl": pnl,
        "kind": "trade",
        "ts": ts,
    }


class JournalApiTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "journal.db")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old

    async def test_a_closed_trip_and_its_note(self) -> None:
        journal_insert_fills([_fill("a", "buy", 1_700_000_000), _fill("b", "sell", 1_700_000_100, "20")])
        journal_insert_funding([{"market_index": 1, "ts": 1_700_000_050, "amount": "2"}])
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            listed = await client.get("/api/journal/trips")
            self.assertEqual(listed.status_code, 200)
            trip = listed.json()["trips"][0]
            self.assertEqual(trip["trip_key"], "1:a")
            self.assertEqual(trip["net"], "20")
            self.assertEqual(trip["funding"], "2")
            self.assertEqual(len(trip["fills"]), 2)
            self.assertFalse(trip["open"])

            noted = await client.put(
                "/api/journal/trips/1:a/note",
                json={"note": "held through the spike", "tags": ["planned"]},
            )
            self.assertEqual(noted.status_code, 200)
            again = await client.get("/api/journal/trips")
            self.assertEqual(again.json()["trips"][0]["note"], "held through the spike")
            self.assertEqual(again.json()["trips"][0]["tags"], ["planned"])

            stats = await client.get("/api/journal/summary", params={"range": "all", "group": "none"})
            self.assertEqual(stats.status_code, 200)
            group = stats.json()["groups"][0]
            self.assertEqual(group["count"], 1)
            self.assertEqual(group["net"], "20")
            self.assertIsNone(group["profit_factor"])
            other = await client.get(
                "/api/journal/summary",
                params={"range": "all", "group": "none", "market": "BTC"},
            )
            self.assertEqual(other.json()["groups"][0]["count"], 0)

            # The trip has no algo, so it is manual: in All and Manual, not in All algos.
            for algo, count in (("", 1), ("manual", 1), ("algos", 0)):
                got = await client.get("/api/journal/trips", params={"algo": algo})
                self.assertEqual(len(got.json()["trips"]), count, algo)

    @patch("mayedge.api.routes.journal.run_sync", new_callable=AsyncMock)
    async def test_sync_starts_without_reading_the_venue_here(self, run_sync: AsyncMock) -> None:
        run_sync.return_value = {"started": False, "last_synced_at": None}
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            res = await client.post("/api/journal/sync")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["started"])
        run_sync.assert_awaited()

    async def test_two_reads_parse_fills_once_until_a_write(self) -> None:
        journal_insert_fills(
            [_fill("a", "buy", 1_700_000_000), _fill("b", "sell", 1_700_000_100, "20")]
        )
        journal_routes._cache = None
        journal_routes._ready = None
        calls = {"n": 0}

        async def counting(fn: Any, *args: Any) -> Any:
            calls["n"] += 1
            return await real_call(fn, *args)

        with patch("mayedge.api.routes.journal.call", counting):
            await journal_routes.get_trips()
            await journal_routes.get_trips()
            self.assertEqual(calls["n"], 1)
            before = journal_generation()
            journal_put_note("1:a", "again", [])
            self.assertGreater(journal_generation(), before)
            await journal_routes.get_trips()
        self.assertEqual(calls["n"], 2)

    async def test_upnl_is_fresh_on_every_request(self) -> None:
        journal_insert_fills([_fill("a", "buy", 1_700_000_000)])
        journal_routes._cache = None
        journal_routes._ready = None
        previous = account_service._summary

        def summary(pnl: str) -> AccountSummary:
            return AccountSummary(
                "0",
                "0",
                pnl,
                positions=[Position(1, "ETH", "1", "100", "100", pnl, 1, "cross")],
            )

        account_service._summary = summary("1.5")
        try:
            first = await journal_routes.get_trips()
            account_service._summary = summary("4")
            second = await journal_routes.get_trips()
        finally:
            account_service._summary = previous
        self.assertEqual(Decimal(first["trips"][0]["upnl"]), Decimal("1.5"))
        self.assertEqual(Decimal(second["trips"][0]["upnl"]), Decimal("4"))

    async def test_warm_covers_the_next_read(self) -> None:
        journal_insert_fills(
            [_fill("a", "buy", 1_700_000_000), _fill("b", "sell", 1_700_000_100, "20")]
        )
        journal_routes._ready = None
        calls = {"n": 0}

        async def counting(fn: Any, *args: Any) -> Any:
            calls["n"] += 1
            return await real_call(fn, *args)

        with patch("mayedge.api.routes.journal.call", counting):
            await journal_routes.warm()
            await journal_routes.get_trips()
        self.assertEqual(calls["n"], 1)

    async def test_a_slow_rebuild_stays_off_the_loop(self) -> None:
        journal_routes._ready = None
        started = time.perf_counter()
        with patch("mayedge.api.routes.journal.build_off_loop", _hold_the_gil):
            await assert_loop_free(journal_routes.get_trips(), max_gap_ms=20)
        self.assertGreaterEqual(time.perf_counter() - started, 0.08)

    async def test_rebuild_does_not_import_the_gateway(self) -> None:
        store.init_db()
        close_pool(wait=True)
        journal_routes._ready = None
        loaded = await real_call(imports_gateway, settings.db_path, {})
        self.assertIs(loaded, False)
