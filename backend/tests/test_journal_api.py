"""The journal routes rebuild stored fills and do not talk to the venue on a read."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge import db as store
from mayedge.api.app import create_app
from mayedge.config import settings
from mayedge.persist_journal import journal_insert_fills, journal_insert_funding


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
