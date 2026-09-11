from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge import desk
from mayedge.algos.book import find_book, find_book_by_algo_id


class DeskRegistryTests(unittest.TestCase):
    def test_books_include_chase_twap_and_ladder(self) -> None:
        types = {book.algo_type for book in desk.books}
        self.assertEqual(types, {"chase-iceberg", "advanced-twap", "ladder"})

    def test_get_book_by_type(self) -> None:
        self.assertIs(desk.get_book("chase-iceberg"), desk.chase_book)
        self.assertIs(desk.get_book("advanced-twap"), desk.twap_book)
        self.assertIs(desk.get_book("ladder"), desk.ladder_book)
        self.assertIsNone(desk.get_book("unknown-algo"))

    def test_find_book_helpers(self) -> None:
        self.assertIs(find_book(desk.books, "advanced-twap"), desk.twap_book)
        self.assertIsNone(find_book_by_algo_id(desk.books, "missing-id"))

    def test_algo_book_merges_working_and_history(self) -> None:
        chase = MagicMock()
        chase.to_dict.return_value = {
            "working": [{"algo_id": "CH-0001", "created_at": 2}],
            "history": [{"algo_id": "CH-0000", "created_at": 10}],
        }
        twap = MagicMock()
        twap.to_dict.return_value = {
            "working": [{"algo_id": "TW-0001", "created_at": 5}],
            "history": [{"algo_id": "TW-0000", "created_at": 1}],
        }
        with patch.object(desk, "books", (chase, twap)):
            payload = desk.algo_book()
        self.assertEqual(payload["type"], "algo")
        self.assertEqual([row["algo_id"] for row in payload["working"]], ["TW-0001", "CH-0001"])
        self.assertEqual([row["algo_id"] for row in payload["history"]], ["CH-0000", "TW-0000"])


class DeskRegistryAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_routes_to_owning_book(self) -> None:
        chase = MagicMock()
        chase.has.return_value = False
        chase.pause = AsyncMock()
        twap = MagicMock()
        twap.has.return_value = True
        twap.pause = AsyncMock()
        twap.to_dict.return_value = {"working": [], "history": []}
        chase.to_dict.return_value = {"working": [], "history": []}
        with patch.object(desk, "books", (chase, twap)):
            await desk.pause_algo("TW-0001")
        twap.pause.assert_awaited_once_with("TW-0001")
        chase.pause.assert_not_called()

    async def test_pause_unknown_algo_raises(self) -> None:
        chase = MagicMock()
        chase.has.return_value = False
        twap = MagicMock()
        twap.has.return_value = False
        with patch.object(desk, "books", (chase, twap)), self.assertRaises(ValueError):
            await desk.pause_algo("missing")

    async def test_stop_algo_iterates_all_books(self) -> None:
        chase = MagicMock()
        chase.stop = AsyncMock()
        chase.to_dict.return_value = {"working": [], "history": []}
        twap = MagicMock()
        twap.stop = AsyncMock()
        twap.to_dict.return_value = {"working": [], "history": []}
        with patch.object(desk, "books", (chase, twap)):
            await desk.stop_algo("CH-0001")
        chase.stop.assert_awaited_once_with("CH-0001")
        twap.stop.assert_awaited_once_with("CH-0001")

    async def test_pause_for_market_iterates_all_books(self) -> None:
        chase = MagicMock()
        chase.pause_for_market = AsyncMock()
        twap = MagicMock()
        twap.pause_for_market = AsyncMock()
        with patch.object(desk, "books", (chase, twap)):
            await desk.pause_for_market(7)
        chase.pause_for_market.assert_awaited_once_with(7)
        twap.pause_for_market.assert_awaited_once_with(7)
