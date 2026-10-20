"""Pieces the algo test fakes share.

Chase, grid, ladder and TWAP drive ``FakeOrderService`` in ``chase_harness``.
Planner and Trail drive ``FakeVenue`` in ``planner_harness``. Those two order
books speak different methods, so they stay where the tests already import
them. The clock is the same object.
"""

from __future__ import annotations

from dataclasses import dataclass

from mayedge.lighter.models import MarketMeta


@dataclass
class FakeClock:
    now_ms: int = 1_000_000

    def advance(self, ms: int) -> None:
        self.now_ms += ms

    def __call__(self) -> int:
        return self.now_ms


def eth_market() -> MarketMeta:
    return MarketMeta(
        market_index=1,
        symbol="ETH",
        price_decimals=2,
        size_decimals=1,
        min_base_amount=0.1,
        min_quote_amount=0.0,
    )
