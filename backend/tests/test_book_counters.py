from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from mayedge import db as store
from mayedge.algos.chase.book import ChaseBook
from mayedge.algos.chase.config import CHASE_COI_BASE
from mayedge.algos.grid.book import ChaseGridBook
from mayedge.algos.grid.config import GRID_COI_BASE
from mayedge.algos.ladder.book import LadderBook
from mayedge.algos.ladder.config import LADDER_COI_BASE
from mayedge.config import settings

# (book class, algo_type, id prefix, coi base)
BOOKS: list[tuple[Callable[..., Any], str, str, int]] = [
    (ChaseBook, "chase-iceberg", "CH-", CHASE_COI_BASE),
    (LadderBook, "ladder", "LD-", LADDER_COI_BASE),
    (ChaseGridBook, "chase-grid", "CG-", GRID_COI_BASE),
]


def _make(cls: Callable[..., Any]) -> Any:
    return cls(execution=MagicMock(), broadcast=lambda _payload: None)


def _archive_run(algo_id: str, algo_type: str, coi: int) -> None:
    store.upsert_run(
        {
            "algo_id": algo_id,
            "algo_type": algo_type,
            "status": "stopped",
            "market_index": 1,
            "symbol": "ETH",
            "side": "buy",
            "qty": "1",
            "remaining": "0",
            "filled": "1",
            "created_at": 1,
        },
        next_clip=2,
        next_fill=1,
        trade_ids=set(),
        trade_qty_by_clip={},
        clips=[
            {
                "seq": 1,
                "client_order_index": coi,
                "price": "100",
                "qty": "1",
                "status": "filled",
            }
        ],
        fills=[],
        archived=True,
    )


class BookCounterRestartTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self._db = patch.object(settings, "db_path", str(Path(self._td.name) / "mayedge.db"))
        self._db.start()
        store.close_db()
        store.init_db()

    def tearDown(self) -> None:
        store.close_db()
        self._db.stop()
        self._td.cleanup()

    async def _restart(self, cls: Callable[..., Any]) -> Any:
        store.close_db()
        book = _make(cls)
        await book.restore()
        return book

    async def test_a_lower_save_by_another_book_does_not_rewind_a_book(self) -> None:
        for cls, _algo_type, prefix, coi_base in BOOKS:
            with self.subTest(book=cls.__name__):
                store.close_db()
                store.init_db()
                book = await self._restart(cls)
                last_id, last_coi = "", 0
                for _ in range(5):
                    last_id = book.alloc_id()
                    last_coi = book.alloc_coi()
                # Another book saves its lower counters last, the old way and the new way.
                store.save_counters(1, 1)
                store.save_book_counters("someone-else", 1, 1)

                book = await self._restart(cls)
                next_id = book.alloc_id()
                next_coi = book.alloc_coi()
                self.assertGreater(next_id, last_id)
                self.assertTrue(next_id.startswith(prefix))
                self.assertGreater(next_coi, last_coi)
                self.assertEqual(next_coi, last_coi + 1)
                self.assertGreater(last_coi, coi_base)

    async def test_books_keep_separate_sequences_across_a_restart(self) -> None:
        chase, ladder = await self._restart(ChaseBook), await self._restart(LadderBook)
        for _ in range(7):
            chase.alloc_id()
            chase.alloc_coi()
        ladder.alloc_id()
        ladder.alloc_coi()

        chase, ladder = await self._restart(ChaseBook), await self._restart(LadderBook)
        self.assertEqual(chase.alloc_id(), "CH-0008")
        self.assertEqual(chase.alloc_coi(), CHASE_COI_BASE + 8)
        self.assertEqual(ladder.alloc_id(), "LD-0002")
        self.assertEqual(ladder.alloc_coi(), LADDER_COI_BASE + 2)

    async def test_first_load_seeds_above_the_shared_keys(self) -> None:
        for cls, algo_type, prefix, coi_base in BOOKS:
            with self.subTest(book=cls.__name__):
                store.save_counters(30, 40)
                key = algo_type
                with store._lock:
                    conn = store._connect()
                    conn.execute(
                        "DELETE FROM meta WHERE key IN (?, ?)", (f"{key}_id_seq", f"{key}_coi_seq")
                    )
                    conn.commit()
                book = await self._restart(cls)
                self.assertEqual(book.alloc_id(), f"{prefix}0031")
                self.assertEqual(book.alloc_coi(), coi_base + 41)

    async def test_first_load_seeds_above_ids_and_cois_already_in_rows(self) -> None:
        for cls, algo_type, prefix, coi_base in BOOKS:
            with self.subTest(book=cls.__name__):
                # The shared keys were rewound by another book; this book's rows went higher.
                store.save_counters(3, 5)
                _archive_run(f"{prefix}0009", algo_type, coi_base + 12)
                book = await self._restart(cls)
                self.assertEqual(book.alloc_id(), f"{prefix}0010")
                self.assertEqual(book.alloc_coi(), coi_base + 13)
                self.assertEqual(
                    store.load_book_counters(algo_type), {"id_seq": 10, "coi_seq": 13}
                )

    async def test_seeding_ignores_other_books_rows(self) -> None:
        _archive_run("LD-0050", "ladder", LADDER_COI_BASE + 60)
        chase = await self._restart(ChaseBook)
        self.assertEqual(chase.alloc_id(), "CH-0001")
        self.assertEqual(chase.alloc_coi(), CHASE_COI_BASE + 1)

    async def test_seeding_runs_once(self) -> None:
        store.save_counters(20, 20)
        chase = await self._restart(ChaseBook)
        self.assertEqual(store.load_book_counters("chase-iceberg"), {"id_seq": 20, "coi_seq": 20})
        chase.alloc_id()
        store.save_counters(99, 99)
        await self._restart(ChaseBook)
        self.assertEqual(store.load_book_counters("chase-iceberg")["id_seq"], 21)
        self.assertEqual(store.load_counters()["id_seq"], 99)
