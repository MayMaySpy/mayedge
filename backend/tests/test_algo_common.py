"""Shared algo helpers."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from mayedge.algos.common import in_coi_range, now_ms, venue_order_keys


class CommonTests(unittest.TestCase):
    def test_now_ms_is_the_wall_clock(self) -> None:
        before = int(time.time() * 1000)
        got = now_ms()
        after = int(time.time() * 1000)
        self.assertGreaterEqual(got, before)
        self.assertLessEqual(got, after)

    def test_coi_range_is_half_open(self) -> None:
        self.assertTrue(in_coi_range(8_000_000_000, 8_000_000_000, 9_000_000_000))
        self.assertFalse(in_coi_range(9_000_000_000, 8_000_000_000, 9_000_000_000))
        self.assertFalse(in_coi_range(None, 8_000_000_000, 9_000_000_000))

    def test_order_keys_drop_a_missing_index(self) -> None:
        rows = [
            {"market_index": 1, "order_index": 10, "client_order_index": 5},
            {"market_index": 1, "order_index": 0, "client_order_index": 6},
            {"market_index": 1, "order_index": 11, "client_order_index": 99},
            None,
        ]
        keys = venue_order_keys(rows, lambda coi: coi in {5, 6})
        self.assertEqual(keys, [(1, 10)])

    def test_order_keys_can_keep_an_unindexed_row(self) -> None:
        rows = [
            SimpleNamespace(market_index=2, order_index=0, client_order_index=7),
            {"market_index": 2, "order_index": 12, "client_order_index": 8},
        ]
        keys = venue_order_keys(rows, lambda coi: True, keep_unindexed=True)
        self.assertEqual(keys, [(2, 7), (2, 12)])
