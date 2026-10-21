from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mayedge import db as store
from mayedge.config import settings
from mayedge.lighter.models import MarketMeta
from mayedge.persist_oi import (
    _FOLD_INSERT,
    OI_DAY_S,
    OI_DETAIL_MS,
    OI_HOUR_MS,
    OI_HOUR_S,
    OI_MINUTE_S,
    flush_open_interest,
    fold_open_interest,
    list_open_interest,
    open_interest_sample_rows,
)


def _market(
    index: int,
    symbol: str,
    *,
    oi: float | None,
    market_type: str = "perp",
) -> MarketMeta:
    meta = MarketMeta(index, symbol, 2, 4, 0.001, 10.0, market_type=market_type)
    meta.open_interest = oi
    return meta


class OpenInterestStoreTests(unittest.TestCase):
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

    def test_sample_rows_skip_spot_and_missing(self) -> None:
        rows = open_interest_sample_rows(
            [
                _market(1, "ETH", oi=100.0),
                _market(2, "ETH", oi=50.0, market_type="spot"),
                _market(3, "SOL", oi=None),
                _market(4, "BTC", oi=0.0),
            ]
        )
        self.assertEqual(rows, [{"market_index": 1, "symbol": "ETH", "oi_usd": 100.0}])

    def test_flush_overwrites_the_same_minute(self) -> None:
        self.assertEqual(
            flush_open_interest(
                [{"market_index": 1, "symbol": "ETH", "oi_usd": 100.0}],
                minute_index=10,
            ),
            1,
        )
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 140.0}],
            minute_index=10,
        )
        rows = list_open_interest(1, resolution="1m", count=10)
        self.assertEqual(rows, [{"time": 600, "open_interest": 140.0}])

    def test_list_uses_last_sample_in_a_coarser_bucket(self) -> None:
        for minute, oi in ((0, 10.0), (1, 20.0), (4, 30.0), (5, 40.0)):
            flush_open_interest(
                [{"market_index": 1, "symbol": "ETH", "oi_usd": oi}],
                minute_index=minute,
            )
        rows = list_open_interest(1, resolution="5m", count=10)
        self.assertEqual(
            rows,
            [
                {"time": 0, "open_interest": 30.0},
                {"time": 300, "open_interest": 40.0},
            ],
        )

    def test_list_omits_minutes_that_were_not_sampled(self) -> None:
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 10.0}],
            minute_index=0,
        )
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 12.0}],
            minute_index=3,
        )
        rows = list_open_interest(1, resolution="1m", count=10)
        self.assertEqual([r["time"] for r in rows], [0, 180])

    def test_folds_a_finished_hour_older_than_30_days(self) -> None:
        now = 100 * OI_DAY_S * 1000
        old_hour = (now - OI_DETAIL_MS) // (OI_HOUR_S * 1000) - 1
        first = old_hour * (OI_HOUR_S // 60)
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 100.0}],
            minute_index=first,
        )
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 250.0}],
            minute_index=first + 10,
        )
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETHEREUM", "oi_usd": 180.0}],
            minute_index=first + 50,
        )
        kept = (old_hour + 1) * (OI_HOUR_S // 60)
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 90.0}],
            minute_index=kept,
        )
        flush_open_interest(
            [{"market_index": 2, "symbol": "BTC", "oi_usd": 5.0}],
            minute_index=first,
        )
        self.assertEqual(fold_open_interest(now_ms=now), 4)

        rows = list_open_interest(1, resolution="1m", count=10)
        self.assertEqual(rows, [{"time": kept * 60, "open_interest": 90.0}])

        hours = list_open_interest(1, resolution="1h", count=10)
        self.assertEqual(
            hours,
            [
                {"time": old_hour * OI_HOUR_S, "open_interest": 180.0},
                {"time": (old_hour + 1) * OI_HOUR_S, "open_interest": 90.0},
            ],
        )
        with store._lock:
            conn = store._connect()
            hour = conn.execute(
                "SELECT symbol, oi_high, oi_low, oi_close FROM oi_hours WHERE market_index = 1"
            ).fetchone()
            btc = conn.execute(
                "SELECT oi_close FROM oi_hours WHERE market_index = 2"
            ).fetchone()
        self.assertEqual(hour["symbol"], "ETHEREUM")
        self.assertEqual(hour["oi_high"], 250.0)
        self.assertEqual(hour["oi_low"], 100.0)
        self.assertEqual(hour["oi_close"], 180.0)
        self.assertEqual(btc["oi_close"], 5.0)

    def test_folded_hours_keep_every_coarse_chart_past_30_days(self) -> None:
        now = 100 * OI_DAY_S * 1000
        old_day = (now - OI_DETAIL_MS) // (OI_DAY_S * 1000) - 5
        for hour, oi in [(0, 10.0), (3, 20.0), (5, 30.0), (23, 40.0)]:
            flush_open_interest(
                [{"market_index": 1, "symbol": "ETH", "oi_usd": oi}],
                minute_index=(old_day * 24 + hour) * 60 + 30,
            )
        fold_open_interest(now_ms=now)
        day_s = old_day * OI_DAY_S
        self.assertEqual(
            list_open_interest(1, resolution="1d", count=10),
            [{"time": day_s, "open_interest": 40.0}],
        )
        self.assertEqual(
            list_open_interest(1, resolution="4h", count=10),
            [
                {"time": day_s, "open_interest": 20.0},
                {"time": day_s + 4 * OI_HOUR_S, "open_interest": 30.0},
                {"time": day_s + 20 * OI_HOUR_S, "open_interest": 40.0},
            ],
        )
        # Minute charts do not stretch hourly closes past the 30-day detail.
        self.assertEqual(list_open_interest(1, resolution="15m", count=10), [])

    def test_fold_is_idempotent_for_the_same_hour(self) -> None:
        now = 100 * OI_DAY_S * 1000
        old_hour = (now - OI_DETAIL_MS) // (OI_HOUR_S * 1000) - 1
        minute = old_hour * (OI_HOUR_S // 60)
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 40.0}],
            minute_index=minute,
        )
        self.assertEqual(fold_open_interest(now_ms=now), 1)
        self.assertEqual(fold_open_interest(now_ms=now), 0)
        hours = list_open_interest(1, resolution="1h", count=10)
        self.assertEqual(hours, [{"time": old_hour * OI_HOUR_S, "open_interest": 40.0}])

    def test_rejects_unknown_resolution(self) -> None:
        with self.assertRaises(ValueError):
            list_open_interest(1, resolution="1s", count=10)

    def test_fold_searches_the_minute_index(self) -> None:
        with store._lock:
            conn = store._connect()
            statements = [
                (_FOLD_INSERT, (OI_MINUTE_S, OI_HOUR_S, 0, 60)),
                (
                    "DELETE FROM oi_samples WHERE minute_index >= ? AND minute_index < ?",
                    (0, 60),
                ),
                (
                    "SELECT MIN(minute_index) AS minute FROM oi_samples WHERE minute_index < ?",
                    (60,),
                ),
            ]
            details: list[str] = []
            for sql, params in statements:
                details.extend(str(row[-1]) for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params))
        for line in details:
            if "oi_samples" not in line:
                continue
            self.assertIn("SEARCH", line)
            self.assertNotIn("SCAN", line)
            self.assertIn("minute_index<?", line)

    def test_new_fold_matches_the_old_sql(self) -> None:
        now = 100 * OI_DAY_S * 1000
        fold_before = (now - OI_DETAIL_MS) // OI_HOUR_MS
        for minute, oi in (
            ((fold_before - 5) * 60, 10.0),
            (fold_before * 60 - 1, 20.0),
            (fold_before * 60, 30.0),
        ):
            flush_open_interest(
                [{"market_index": 1, "symbol": "ETH", "oi_usd": oi}],
                minute_index=minute,
            )
        flush_open_interest(
            [{"market_index": 2, "symbol": "BTC", "oi_usd": 5.0}],
            minute_index=(fold_before - 5) * 60,
        )
        dst = sqlite3.connect(str(Path(self._td.name) / "old.db"))
        try:
            with store._lock:
                store._connect().backup(dst)
            fold_open_interest(now_ms=now)
            _fold_old(dst, now)
            with store._lock:
                self.assertEqual(_oi_rows(store._connect()), _oi_rows(dst))
        finally:
            dst.close()

    def test_chunked_fold_matches_one_pass_over_three_days(self) -> None:
        now = 100 * OI_DAY_S * 1000
        fold_before = (now - OI_DETAIL_MS) // OI_HOUR_MS
        cutoff = fold_before * (OI_HOUR_S // OI_MINUTE_S)
        for day in range(3):
            for hour in (0, 11, 23):
                minute = (fold_before - 72 + day * 24 + hour) * 60 + 7
                flush_open_interest(
                    [{"market_index": 1, "symbol": "ETH", "oi_usd": float(day * 100 + hour)}],
                    minute_index=minute,
                )
        flush_open_interest(
            [{"market_index": 1, "symbol": "ETH", "oi_usd": 1.0}],
            minute_index=cutoff,
        )
        dst = sqlite3.connect(str(Path(self._td.name) / "one-pass.db"))
        try:
            with store._lock:
                store._connect().backup(dst)
            fold_open_interest(now_ms=now)
            dst.execute(_FOLD_INSERT, (OI_MINUTE_S, OI_HOUR_S, 0, cutoff))
            dst.execute("DELETE FROM oi_samples WHERE minute_index < ?", (cutoff,))
            dst.commit()
            with store._lock:
                self.assertEqual(_oi_rows(store._connect()), _oi_rows(dst))
        finally:
            dst.close()


_OLD_INSERT = """
    WITH foldable AS (
        SELECT
            market_index,
            symbol,
            minute_index,
            oi_usd,
            (minute_index * ?) / ? AS hour_index
        FROM oi_samples
        WHERE (minute_index * ?) / ? < ?
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY hour_index, market_index
                ORDER BY minute_index DESC
            ) AS rn
        FROM foldable
    )
    INSERT INTO oi_hours (hour_index, market_index, symbol, oi_high, oi_low, oi_close)
    SELECT
        hour_index,
        market_index,
        MAX(CASE WHEN rn = 1 THEN symbol END),
        MAX(oi_usd),
        MIN(oi_usd),
        MAX(CASE WHEN rn = 1 THEN oi_usd END)
    FROM ranked
    GROUP BY hour_index, market_index
    ON CONFLICT(hour_index, market_index) DO UPDATE SET
        symbol = excluded.symbol,
        oi_high = CASE
            WHEN excluded.oi_high > oi_hours.oi_high THEN excluded.oi_high
            ELSE oi_hours.oi_high
        END,
        oi_low = CASE
            WHEN excluded.oi_low < oi_hours.oi_low THEN excluded.oi_low
            ELSE oi_hours.oi_low
        END,
        oi_close = excluded.oi_close
"""

_OLD_DELETE = """
    DELETE FROM oi_samples
    WHERE (minute_index * ?) / ? < ?
"""


def _fold_old(conn: sqlite3.Connection, now_ms: int) -> None:
    fold_before_hour = (int(now_ms) - OI_DETAIL_MS) // OI_HOUR_MS
    conn.execute(
        _OLD_INSERT,
        (OI_MINUTE_S, OI_HOUR_S, OI_MINUTE_S, OI_HOUR_S, int(fold_before_hour)),
    )
    conn.execute(_OLD_DELETE, (OI_MINUTE_S, OI_HOUR_S, int(fold_before_hour)))
    conn.commit()


def _oi_rows(conn: sqlite3.Connection) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    hours = [
        tuple(row)
        for row in conn.execute(
            """
            SELECT hour_index, market_index, symbol, oi_high, oi_low, oi_close
            FROM oi_hours ORDER BY hour_index, market_index
            """
        )
    ]
    samples = [
        tuple(row)
        for row in conn.execute(
            """
            SELECT market_index, minute_index, symbol, oi_usd
            FROM oi_samples ORDER BY minute_index, market_index
            """
        )
    ]
    return hours, samples
