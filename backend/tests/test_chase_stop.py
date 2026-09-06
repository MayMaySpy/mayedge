from unittest import TestCase

from mayedge.algos.chase.config import CHASE_COI_BASE
from mayedge.algos.chase.util import _chase_order_keys, is_chase_client_order


class ChaseStopSweepTests(TestCase):
    def test_coi_range(self) -> None:
        self.assertTrue(is_chase_client_order(CHASE_COI_BASE))
        self.assertTrue(is_chase_client_order(CHASE_COI_BASE + 12))
        self.assertFalse(is_chase_client_order(CHASE_COI_BASE - 1))
        self.assertFalse(is_chase_client_order(9_000_000_000))
        self.assertFalse(is_chase_client_order(None))

    def test_keys_from_dicts_and_objects(self) -> None:
        class Row:
            def __init__(self) -> None:
                self.client_order_index = CHASE_COI_BASE + 2
                self.market_index = 3
                self.order_index = 44

        keys = _chase_order_keys(
            [
                {
                    "client_order_index": CHASE_COI_BASE + 1,
                    "market_index": 7,
                    "order_index": 99,
                },
                {
                    "client_order_index": 12,
                    "market_index": 7,
                    "order_index": 100,
                },
                {
                    "client_order_index": CHASE_COI_BASE + 3,
                    "market_index": 7,
                    "order_index": 0,
                },
                Row(),
            ]
        )
        self.assertEqual(keys, [(7, 99), (3, 44)])

    def test_keys_filter_by_cois(self) -> None:
        keys = _chase_order_keys(
            [
                {
                    "client_order_index": CHASE_COI_BASE + 1,
                    "market_index": 1,
                    "order_index": 10,
                },
                {
                    "client_order_index": CHASE_COI_BASE + 2,
                    "market_index": 1,
                    "order_index": 11,
                },
            ],
            cois={CHASE_COI_BASE + 2},
        )
        self.assertEqual(keys, [(1, 11)])
