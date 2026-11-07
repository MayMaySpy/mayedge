from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mayedge import desk
from mayedge.algos.book import find_book, find_book_by_algo_id


class DeskRegistryTests(unittest.TestCase):
    def test_books_include_chase_twap_ladder_grid_planner_and_trail(self) -> None:
        types = {book.algo_type for book in desk.books}
        self.assertEqual(
            types,
            {
                "chase-iceberg",
                "advanced-twap",
                "ladder",
                "chase-grid",
                "planner",
                "trail",
                "massager",
            },
        )

    def test_trail_refuses_beside_planner_or_grid(self) -> None:
        """Trail S1, both ways; Chase beside it is fine."""
        conflict = desk.trail_book._market_conflict
        assert conflict is not None
        with patch.object(desk.planner_book, "live_on_market", return_value=True):
            self.assertTrue(conflict(1))
        with patch.object(desk.grid_book, "live_on_market", return_value=True):
            self.assertTrue(conflict(1))
        with patch.object(desk.chase_book, "live_on_market", return_value=True):
            self.assertFalse(conflict(1))
        with patch.object(desk.trail_book, "live_on_market", return_value=True):
            self.assertTrue(desk._market_has_other_desk_algo(desk.planner_book)(1))
            self.assertTrue(desk.grid_book._market_conflict(1))  # pyright: ignore[reportOptionalCall]

    def test_grid_and_planner_each_refuse_beside_another_algo(self) -> None:
        """Grid G1 and Planner S5: Grid refuses beside a Planner or Trail; Planner beside anything."""
        grid_conflict = desk.grid_book._market_conflict
        assert grid_conflict is not None
        with patch.object(desk.planner_book, "live_on_market", return_value=True):
            self.assertTrue(grid_conflict(1))
            self.assertTrue(desk.planner_owns_exit(1))
        with patch.object(desk.trail_book, "live_on_market", return_value=True):
            self.assertTrue(grid_conflict(1))
        with patch.object(desk.grid_book, "live_on_market", return_value=True):
            self.assertTrue(desk._market_has_other_desk_algo(desk.planner_book)(1))

    def test_grid_runs_beside_chase_ladder_and_twap(self) -> None:
        """Grid G1: a Ladder buy, a Grid and a Ladder sell can share a Market."""
        grid_conflict = desk.grid_book._market_conflict
        assert grid_conflict is not None
        for book in (desk.chase_book, desk.ladder_book, desk.twap_book):
            with patch.object(book, "live_on_market", return_value=True):
                self.assertFalse(grid_conflict(1), book.algo_type)

    def test_massager_refuses_beside_planner_trail_or_grid(self) -> None:
        """Massager MS18, both ways; Chase, Ladder and TWAP beside it are fine."""
        conflict = desk.massager_book._market_conflict
        assert conflict is not None
        for book in (desk.planner_book, desk.trail_book, desk.grid_book):
            with patch.object(book, "live_on_market", return_value=True):
                self.assertTrue(conflict(1), book.algo_type)
        for book in (desk.chase_book, desk.ladder_book, desk.twap_book):
            with patch.object(book, "live_on_market", return_value=True):
                self.assertFalse(conflict(1), book.algo_type)
        with patch.object(desk.massager_book, "live_on_market", return_value=True):
            for book in (desk.grid_book, desk.trail_book):
                book_conflict = book._market_conflict
                assert book_conflict is not None
                self.assertTrue(book_conflict(1), book.algo_type)
            self.assertTrue(desk._market_has_other_desk_algo(desk.planner_book)(1))

    def test_get_book_by_type(self) -> None:
        self.assertIs(desk.get_book("chase-iceberg"), desk.chase_book)
        self.assertIs(desk.get_book("advanced-twap"), desk.twap_book)
        self.assertIs(desk.get_book("ladder"), desk.ladder_book)
        self.assertIs(desk.get_book("chase-grid"), desk.grid_book)
        self.assertIs(desk.get_book("planner"), desk.planner_book)
        self.assertIs(desk.get_book("trail"), desk.trail_book)
        self.assertIs(desk.get_book("massager"), desk.massager_book)
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

    async def test_restore_publishes_once_after_every_book(self) -> None:
        broadcasts: list[dict[str, Any]] = []
        chase = MagicMock()
        twap = MagicMock()

        async def chase_restore() -> None:
            desk._publish_algo_book({})

        async def twap_restore() -> None:
            desk._publish_algo_book({})

        chase.restore = chase_restore
        twap.restore = twap_restore
        chase.to_dict.return_value = {
            "working": [],
            "history": [{"algo_id": "CH-0001", "created_at": 1, "status": "done"}],
        }
        twap.to_dict.return_value = {
            "working": [],
            "history": [{"algo_id": "TW-0001", "created_at": 2, "status": "done"}],
        }
        with (
            patch.object(desk, "books", (chase, twap)),
            patch.object(desk, "_broadcast", broadcasts.append),
        ):
            await desk.restore()
        self.assertEqual(len(broadcasts), 1)
        self.assertEqual(
            [row["algo_id"] for row in broadcasts[0]["history"]],
            ["TW-0001", "CH-0001"],
        )
        self.assertFalse(desk._restoring)

    async def test_pause_for_market_iterates_all_books(self) -> None:
        chase = MagicMock()
        chase.pause_for_market = AsyncMock()
        twap = MagicMock()
        twap.pause_for_market = AsyncMock()
        with patch.object(desk, "books", (chase, twap)):
            await desk.pause_for_market(7)
        chase.pause_for_market.assert_awaited_once_with(7)
        twap.pause_for_market.assert_awaited_once_with(7)
