from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge import db as store
from mayedge.algos.planner.book import PlannerBook
from mayedge.algos.planner.plan import PlanRefused
from mayedge.config import settings

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from planner_harness import MI, FakeVenue  # noqa: E402

BODY = {
    "market_index": MI,
    "mode": "enter",
    "side": "buy",
    "entry_type": "limit",
    "entry_price": "100",
    "stop": "95",
    "risk_pct": "1",
    "targets": [{"kind": "r", "value": "2", "pct": "50"}, {"kind": "r", "value": "3", "pct": "50"}],
}


class PlannerBookTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self._db = patch.object(settings, "db_path", str(Path(self._td.name) / "mayedge.db"))
        self._db.start()
        store.close_db()
        store.init_db()
        self.venue = FakeVenue()
        self.sent: list[dict[str, object]] = []
        self.book = PlannerBook(execution=self.venue.execution, broadcast=self.sent.append)

    def tearDown(self) -> None:
        store.close_db()
        self._db.stop()
        self._td.cleanup()

    def test_preview_draws_the_plan_and_sends_nothing(self) -> None:
        out = self.book.preview_from_body(BODY)
        self.assertIsNone(out["refused"])
        plan = out["plan"]
        assert isinstance(plan, dict)
        # 1% of 10000 over R 5 is 20.
        self.assertEqual(plan["size"], "20")
        self.assertEqual([t["price"] for t in plan["targets"]], ["110", "115"])
        self.assertEqual(self.venue.calls, [])

    def test_preview_says_which_rule_a_plan_breaks(self) -> None:
        out = self.book.preview_from_body({**BODY, "stop": "101"})
        self.assertEqual(
            out["refused"],
            {"rule": "S1", "message": "The stop must be on the losing side of entry"},
        )

    async def test_one_planner_per_market(self) -> None:
        await self.book.start_from_body(BODY)
        self.assertTrue(self.book.live_on_market(MI))
        with self.assertRaises(PlanRefused) as caught:
            await self.book.start_from_body(BODY)
        self.assertEqual(caught.exception.rule, "S5")
        self.assertEqual(self.book.preview_from_body(BODY)["refused"]["rule"], "S5")
        await self.book.stop()

    async def test_planner_refuses_beside_another_desk_algo(self) -> None:
        self.book.set_market_conflict(lambda mi: mi == MI)
        with self.assertRaises(PlanRefused) as caught:
            await self.book.start_from_body(BODY)
        self.assertEqual(caught.exception.rule, "S5")
        self.assertEqual(self.venue.calls, [])

    async def test_planner_counters_are_its_own(self) -> None:
        store.save_counters(40, 900)
        self.book.alloc_id()
        self.book.alloc_coi()
        self.assertEqual(store.load_book_counters("planner"), {"id_seq": 1, "coi_seq": 1})
        self.assertEqual(store.load_counters()["coi_seq"], 900)

    async def test_cancel_all_on_its_market_stops_the_planner(self) -> None:
        await self.book.start_from_body(BODY)
        await self.book.pause_for_market(MI)
        self.assertFalse(self.book.live_on_market(MI))
        self.assertEqual(self.venue.orders, {})
        history = self.book.to_dict()["history"]
        assert isinstance(history, list)
        self.assertEqual(history[0]["status"], "stopped")
