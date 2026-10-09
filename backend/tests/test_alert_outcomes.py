from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mayedge import db as store
from mayedge.alert_outcomes import (
    MemoryOutcomeStore,
    OutcomeBook,
    ResolvedOutcome,
    SqliteOutcomeStore,
)
from mayedge.config import settings
from mayedge.lighter.models import Candle

_ENTRY = 1_800_000_000


def _bar(t: int, close: float) -> Candle:
    return Candle(t, close, close, close, close, 1.0)


def _open(book: OutcomeBook, episode_id: str, *, beta: float = 0.0, setup: str = "pump") -> None:
    book.open(
        episode_id=episode_id,
        market_index=1,
        symbol="ETH",
        setup=setup,
        direction="up",
        entry_bar=_ENTRY,
        entry_close=100.0,
        beta=beta,
        opened_at=_ENTRY * 1000,
    )


class OutcomeBookTest(unittest.TestCase):
    def test_resolves_when_the_five_and_fifteen_minute_bars_close(self) -> None:
        saved = MemoryOutcomeStore()
        book = OutcomeBook(store=saved)
        _open(book, "sig-1")
        book.resolve(
            1,
            [_bar(_ENTRY, 100), _bar(_ENTRY + 300, 102), _bar(_ENTRY + 360, 102)],
            {},
            now=_ENTRY + 400,
        )
        early = saved.since(0)
        self.assertEqual([row.horizon_min for row in early], [5])
        self.assertAlmostEqual(early[0].raw_pct, 2.0)
        self.assertAlmostEqual(early[0].excess_pct, 2.0)
        self.assertTrue(early[0].hit)

        book.resolve(
            1,
            [
                _bar(_ENTRY, 100),
                _bar(_ENTRY + 300, 102),
                _bar(_ENTRY + 900, 101),
                _bar(_ENTRY + 960, 101),
            ],
            {},
            now=_ENTRY + 1000,
        )
        by_horizon = {row.horizon_min: row for row in saved.since(0)}
        self.assertEqual(set(by_horizon), {5, 15})
        self.assertAlmostEqual(by_horizon[15].excess_pct, 1.0)
        self.assertTrue(by_horizon[15].hit)

    def test_the_forming_horizon_bar_does_not_resolve(self) -> None:
        saved = MemoryOutcomeStore()
        book = OutcomeBook(store=saved, horizons=(5,))
        _open(book, "sig-1")
        book.resolve(
            1,
            [_bar(_ENTRY, 100), _bar(_ENTRY + 300, 110)],
            {},
            now=_ENTRY + 310,
        )
        self.assertEqual(saved.since(0), [])

    def test_excess_follow_through_subtracts_the_broad_move(self) -> None:
        # Price unchanged. The minute after entry, the board rose 10%. Beta is 2.
        # Excess = 0 - 2 * 10 = -20, so an "up" call did not follow through.
        saved = MemoryOutcomeStore()
        book = OutcomeBook(store=saved, horizons=(5,))
        _open(book, "sig-1", beta=2.0)
        book.resolve(
            1,
            [_bar(_ENTRY, 100), _bar(_ENTRY + 300, 100), _bar(_ENTRY + 360, 100)],
            {_ENTRY + 60: 10.0},
            now=_ENTRY + 400,
        )
        row = saved.since(0)[0]
        self.assertAlmostEqual(row.raw_pct, 0.0)
        self.assertAlmostEqual(row.excess_pct, -20.0)
        self.assertFalse(row.hit)

    def test_stats_are_the_hit_rate_per_setup(self) -> None:
        saved = MemoryOutcomeStore()
        book = OutcomeBook(store=saved)
        _open(book, "hit")
        _open(book, "miss")
        book.resolve(
            1,
            [
                _bar(_ENTRY, 100),
                _bar(_ENTRY + 300, 102),
                _bar(_ENTRY + 360, 102),
                _bar(_ENTRY + 900, 102),
                _bar(_ENTRY + 960, 102),
            ],
            {},
            now=_ENTRY + 1000,
        )
        # The miss episode is the same market, so the bars above resolved both
        # against +2%. Re-open is ignored; write the miss directly.
        saved.save(
            [
                ResolvedOutcome(
                    episode_id="miss",
                    market_index=1,
                    symbol="ETH",
                    setup="pump",
                    direction="up",
                    horizon_min=5,
                    opened_at=_ENTRY * 1000,
                    raw_pct=-1.0,
                    excess_pct=-1.0,
                    hit=False,
                ),
                ResolvedOutcome(
                    episode_id="miss",
                    market_index=1,
                    symbol="ETH",
                    setup="pump",
                    direction="up",
                    horizon_min=15,
                    opened_at=_ENTRY * 1000,
                    raw_pct=-2.0,
                    excess_pct=-2.0,
                    hit=False,
                ),
            ]
        )
        self.assertEqual(
            book.stats(since_ms=0),
            [
                {
                    "setup": "pump",
                    "n": 2,
                    "hit_5m": 0.5,
                    "hit_15m": 0.5,
                    "avg_ex_5m": 0.5,
                    "avg_ex_15m": 0.0,
                }
            ],
        )

    def test_rows_older_than_the_retention_window_are_dropped(self) -> None:
        saved = MemoryOutcomeStore()
        book = OutcomeBook(store=saved, horizons=(5,), retention_days=30)
        saved.save(
            [
                ResolvedOutcome(
                    episode_id="old",
                    market_index=1,
                    symbol="ETH",
                    setup="pump",
                    direction="up",
                    horizon_min=5,
                    opened_at=0,
                    raw_pct=1.0,
                    excess_pct=1.0,
                    hit=True,
                )
            ]
        )
        opened = 40 * 86_400_000
        book.open(
            episode_id="new",
            market_index=1,
            symbol="ETH",
            setup="pump",
            direction="up",
            entry_bar=_ENTRY,
            entry_close=100.0,
            beta=0.0,
            opened_at=opened,
        )
        book.resolve(
            1,
            [_bar(_ENTRY, 100), _bar(_ENTRY + 300, 101), _bar(_ENTRY + 360, 101)],
            {},
            now=_ENTRY + 400,
        )
        self.assertEqual([row.episode_id for row in saved.since(0)], ["new"])


class OutcomeStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        path = str(Path(self._td.name) / "mayedge.db")
        self._patch = patch.object(settings, "db_path", path)
        self._patch.start()
        store.close_db()
        store.init_db()

    def tearDown(self) -> None:
        store.close_db()
        self._patch.stop()
        self._td.cleanup()

    def test_resolved_rows_survive_a_new_store(self) -> None:
        book = OutcomeBook(store=SqliteOutcomeStore(), horizons=(5,))
        _open(book, "sig-1")
        book.resolve(
            1,
            [_bar(_ENTRY, 100), _bar(_ENTRY + 300, 103), _bar(_ENTRY + 360, 103)],
            {},
            now=_ENTRY + 400,
        )
        again = OutcomeBook(store=SqliteOutcomeStore(), horizons=(5,))
        stats = again.stats(since_ms=0)
        self.assertEqual(stats[0]["setup"], "pump")
        self.assertEqual(stats[0]["n"], 1)
        self.assertEqual(stats[0]["hit_5m"], 1.0)
        self.assertAlmostEqual(float(stats[0]["avg_ex_5m"]), 3.0)


if __name__ == "__main__":
    unittest.main()
