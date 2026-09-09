"""Advanced TWAP runner: first slice, skip, styles (fake venue)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge.algos.twap.book import AdvancedTwapBook
from mayedge.algos.twap.plan import AdvancedTwapParams

# Allow `from chase_harness import ...` when discover runs from backend/
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from chase_harness import FakeGateway, FakeOrderService, make_execution  # noqa: E402


def isolated_twap():
    return patch.multiple(
        "mayedge.algos.twap.book.store",
        upsert_run=lambda *a, **k: None,
        load_history=lambda *a, **k: [],
        load_active_runs=lambda *a, **k: [],
        init_db=lambda: None,
    )


class AdvancedTwapJobTests(IsolatedAsyncioTestCase):
    async def test_aggressive_places_a_market_slice(self) -> None:
        with isolated_twap():
            gw = FakeGateway()
            gw.market.mark_price = 100.0
            gw.market.index_price = 100.0
            orders = FakeOrderService()
            book = AdvancedTwapBook(
                execution=lambda: make_execution(gw, orders),
                broadcast=lambda _p: None,
            )
            await book.start(
                market_index=1,
                params=AdvancedTwapParams(
                    side="buy",
                    qty=Decimal("10"),
                    duration_seconds=60,
                    frequency_seconds=30,
                    style="aggressive",
                    randomize=False,
                ),
            )
            self.assertEqual(len(orders.creates), 1)
            self.assertEqual(orders.creates[0]["kind"], "market")
            self.assertEqual(Decimal(orders.creates[0]["size"]), Decimal("10") / Decimal(3))
            job = next(iter(book._jobs.values()))
            self.assertGreater(job.filled, Decimal("0"))
            await book.stop()

    async def test_skips_when_mark_is_through_max_price(self) -> None:
        with isolated_twap():
            gw = FakeGateway()
            gw.market.mark_price = 110.0
            gw.market.index_price = 100.0
            orders = FakeOrderService()
            book = AdvancedTwapBook(
                execution=lambda: make_execution(gw, orders),
                broadcast=lambda _p: None,
            )
            await book.start(
                market_index=1,
                params=AdvancedTwapParams(
                    side="buy",
                    qty=Decimal("10"),
                    duration_seconds=60,
                    frequency_seconds=30,
                    style="aggressive",
                    randomize=False,
                    max_price=Decimal("105"),
                ),
            )
            self.assertEqual(orders.creates, [])
            job = next(iter(book._jobs.values()))
            self.assertEqual(job.reason, "above_max_price")
            await book.stop()

    async def test_passive_posts_at_the_bid(self) -> None:
        with isolated_twap():
            gw = FakeGateway()
            gw.set_book("99.5", "100.5")
            gw.market.mark_price = 100.0
            orders = FakeOrderService()
            book = AdvancedTwapBook(
                execution=lambda: make_execution(gw, orders),
                broadcast=lambda _p: None,
            )
            await book.start(
                market_index=1,
                params=AdvancedTwapParams(
                    side="buy",
                    qty=Decimal("10"),
                    duration_seconds=60,
                    frequency_seconds=30,
                    style="passive",
                    randomize=False,
                ),
            )
            self.assertEqual(len(orders.creates), 1)
            self.assertEqual(orders.creates[0]["time_in_force"], "post_only")
            self.assertEqual(orders.creates[0]["price"], "99.5")
            await book.stop()
            self.assertEqual(len(orders.cancels), 1)
