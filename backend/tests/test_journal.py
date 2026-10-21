"""Round trips rebuild from fills. Rules: docs/journal-rules.md."""

from __future__ import annotations

from decimal import Decimal as D
from unittest import TestCase

from mayedge.journal import Fill, FundingPayment, round_trips, summary

ZERO = D("0")


def fill(**kwargs: object) -> Fill:
    base: dict[str, object] = {
        "trade_id": "1",
        "market_index": 1,
        "symbol": "ETH",
        "side": "buy",
        "is_maker": False,
        "price": D("100"),
        "size": D("1"),
        "usd": D("100"),
        "fee": D("0"),
        "pnl": D("0"),
        "kind": "trade",
        "ts": 1,
    }
    base.update(kwargs)
    return Fill(**base)  # type: ignore[arg-type]


def fund(ts: int, amount: str, market: int = 1) -> FundingPayment:
    return FundingPayment(market_index=market, ts=ts, amount=D(amount))


def recomputed(avg_in: D | None, avg_out: D | None, size: D, *, short: bool = False) -> D:
    assert avg_in is not None and avg_out is not None
    return (avg_in - avg_out) * size if short else (avg_out - avg_in) * size


class RoundTripTests(TestCase):
    def test_open_then_close(self) -> None:
        trips = round_trips(
            [
                fill(trade_id="a", side="buy", price=D("100"), size=D("2"), usd=D("200"), ts=10),
                fill(
                    trade_id="b",
                    side="sell",
                    price=D("110"),
                    size=D("2"),
                    usd=D("220"),
                    fee=D("1"),
                    pnl=D("20"),
                    ts=20,
                ),
            ],
            [],
            {},
            {},
        )
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertEqual(trip.side, "long")
        self.assertFalse(trip.open)
        self.assertFalse(trip.partial)
        self.assertEqual(trip.size, D("2"))
        self.assertEqual(trip.avg_in, D("100"))
        self.assertEqual(trip.avg_out, D("110"))
        self.assertEqual(trip.pnl, D("20"))
        self.assertEqual(trip.net, D("19"))
        self.assertEqual(trip.trip_key, "1:a")
        self.assertEqual(recomputed(trip.avg_in, trip.avg_out, trip.size), trip.pnl)

    def test_scale_in_partial_close_then_close(self) -> None:
        trips = round_trips(
            [
                fill(trade_id="a", price=D("100"), size=D("1"), usd=D("100"), fee=D("1"), ts=1),
                fill(trade_id="b", price=D("120"), size=D("1"), usd=D("120"), fee=D("1"), ts=2),
                fill(
                    trade_id="c",
                    side="sell",
                    price=D("130"),
                    size=D("1"),
                    usd=D("130"),
                    fee=D("1"),
                    pnl=D("20"),
                    ts=3,
                ),
                fill(
                    trade_id="d",
                    side="sell",
                    price=D("140"),
                    size=D("1"),
                    usd=D("140"),
                    fee=D("1"),
                    pnl=D("30"),
                    ts=4,
                ),
            ],
            [],
            {},
            {},
        )
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertFalse(trip.open)
        self.assertEqual(trip.size, D("2"))
        self.assertEqual(trip.avg_in, D("110"))
        self.assertEqual(trip.avg_out, D("135"))
        self.assertEqual(trip.pnl, D("50"))
        self.assertEqual(trip.fees, D("4"))
        self.assertEqual(trip.net, D("46"))
        self.assertEqual(recomputed(trip.avg_in, trip.avg_out, trip.size), trip.pnl)

    def test_a_flip_splits_at_zero_and_shares_the_fee(self) -> None:
        trips = round_trips(
            [
                fill(trade_id="a", price=D("100"), size=D("2"), usd=D("200"), fee=D("2"), ts=1),
                fill(
                    trade_id="b",
                    side="sell",
                    price=D("110"),
                    size=D("3"),
                    usd=D("330"),
                    fee=D("3"),
                    pnl=D("20"),
                    ts=2,
                ),
            ],
            [],
            {},
            {},
        )
        self.assertEqual(len(trips), 2)
        closed, opened = trips
        self.assertEqual(closed.side, "long")
        self.assertFalse(closed.open)
        self.assertEqual(closed.size, D("2"))
        self.assertEqual(closed.fees, D("4"))
        self.assertEqual(closed.pnl, D("20"))
        self.assertEqual(closed.net, D("16"))
        close_part = closed.fills[-1]
        self.assertEqual(close_part.size, D("2"))
        self.assertEqual(close_part.fee, D("2"))
        self.assertEqual(opened.side, "short")
        self.assertTrue(opened.open)
        self.assertEqual(opened.size, D("1"))
        self.assertEqual(opened.fees, D("1"))
        self.assertEqual(opened.pnl, ZERO)
        self.assertEqual(opened.fills[0].trade_id, "b")
        self.assertEqual(recomputed(closed.avg_in, closed.avg_out, closed.size), closed.pnl)
        funded = round_trips(
            [
                fill(trade_id="a", price=D("100"), size=D("2"), usd=D("200"), ts=100),
                fill(
                    trade_id="b",
                    side="sell",
                    price=D("110"),
                    size=D("3"),
                    usd=D("330"),
                    pnl=D("20"),
                    ts=200,
                ),
            ],
            [fund(200, "4"), fund(250, "1")],
            {},
            {},
        )
        self.assertEqual(funded[0].funding, D("4"))
        self.assertEqual(funded[1].funding, D("1"))

    def test_history_starting_mid_position_is_partial(self) -> None:
        trips = round_trips(
            [fill(trade_id="a", side="sell", price=D("90"), pnl=D("10"), fee=D("1"), ts=5)],
            [],
            {},
            {},
        )
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertTrue(trip.partial)
        self.assertEqual(trip.partial_reason, "history starts mid-position")
        self.assertEqual(trip.side, "long")
        self.assertFalse(trip.open)
        self.assertIsNone(trip.avg_in)
        self.assertEqual(trip.pnl, D("10"))

    def test_a_fill_older_than_the_stored_history_is_partial(self) -> None:
        trips = round_trips(
            [
                fill(trade_id="a", ts=1),
                fill(trade_id="b", side="sell", price=D("110"), pnl=D("10"), ts=2),
            ],
            [],
            {},
            {},
            oldest_ts=2,
        )
        self.assertTrue(trips[0].partial)
        self.assertEqual(trips[0].partial_reason, "opened before the stored history")

    def test_an_open_round_trip_carries_live_upnl(self) -> None:
        trips = round_trips(
            [fill(trade_id="a", ts=1)],
            [],
            {},
            {},
            upnl={1: D("5")},
        )
        self.assertTrue(trips[0].open)
        self.assertIsNone(trips[0].close_ts)
        self.assertEqual(trips[0].upnl, D("5"))
        self.assertEqual(summary(trips, "none")[0].count, 0)

    def test_funding_inside_the_window_counts_and_the_flip_boundary_does_not_split(self) -> None:
        trips = round_trips(
            [
                fill(trade_id="a", ts=100, size=D("1"), usd=D("100")),
                fill(
                    trade_id="b",
                    side="sell",
                    price=D("110"),
                    pnl=D("10"),
                    ts=200,
                    size=D("1"),
                    usd=D("110"),
                ),
            ],
            [fund(50, "9"), fund(100, "1"), fund(150, "2"), fund(200, "3"), fund(250, "8")],
            {},
            {},
        )
        self.assertEqual(trips[0].funding, D("6"))
        self.assertEqual(trips[0].net, D("10") + D("6"))

    def test_funding_in_seconds_counts_against_fills_in_ms(self) -> None:
        # The venue stamps fills in ms and funding in seconds (a live LIT trip).
        trips = round_trips(
            [
                fill(trade_id="a", ts=1792514997035, size=D("1"), usd=D("100")),
                fill(
                    trade_id="b",
                    side="sell",
                    price=D("110"),
                    pnl=D("10"),
                    ts=1792516065376,
                    size=D("1"),
                    usd=D("110"),
                ),
            ],
            [fund(1792508400, "-0.023922"), fund(1792515600, "0.136353"), fund(1792519200, "5")],
            {},
            {},
        )
        self.assertEqual(trips[0].funding, D("0.136353"))
        self.assertEqual(trips[0].net, D("10.136353"))

    def test_algo_is_the_family_with_the_most_opening_size(self) -> None:
        trips = round_trips(
            [
                fill(trade_id="a", size=D("1"), ts=1),
                fill(trade_id="b", size=D("3"), ts=2),
                fill(trade_id="c", side="sell", size=D("4"), pnl=D("8"), price=D("102"), ts=3),
            ],
            [],
            {"a": "PL-0001", "b": "CH-0004"},
            {"PL-0001": (D("100"), D("90"))},
        )
        self.assertEqual(trips[0].algo, "chase")
        self.assertEqual(trips[0].algo_id, "CH-0004")
        self.assertIsNone(trips[0].r)

    def test_r_uses_the_stored_stop_and_is_absent_without_one(self) -> None:
        fills = [
            fill(trade_id="a", size=D("2"), usd=D("200"), fee=D("1"), ts=1),
            fill(
                trade_id="b", side="sell", size=D("2"), usd=D("220"), pnl=D("20"), fee=D("1"), ts=2
            ),
        ]
        scored = round_trips(fills, [], {"a": "PL-0002"}, {"PL-0002": (D("100"), D("90"))})
        self.assertEqual(scored[0].algo, "planner")
        # risk = |100 - 90| * 2 = 20. Net = 20 - 2 = 18. R = 0.9.
        self.assertEqual(scored[0].net, D("18"))
        self.assertEqual(scored[0].r, D("18") / D("20"))
        bare = round_trips(fills, [], {"a": "PL-0002"}, {})
        self.assertIsNone(bare[0].r)
        self.assertEqual(bare[0].algo, "planner")

    def test_summary_maths_and_drawdown(self) -> None:
        # Nets: +10, -30, +5. Curve 10, -20, -15. Drawdown 30.
        rows = [
            fill(trade_id="w1", ts=1_700_000_000, usd=D("30"), is_maker=True),
            fill(
                trade_id="w2",
                side="sell",
                ts=1_700_000_100,
                pnl=D("10"),
                usd=D("30"),
                is_maker=True,
                price=D("110"),
            ),
            fill(trade_id="l1", ts=1_700_086_400, usd=D("10"), is_maker=False),
            fill(
                trade_id="l2",
                side="sell",
                ts=1_700_086_500,
                pnl=D("-30"),
                usd=D("10"),
                is_maker=False,
                price=D("70"),
            ),
            fill(trade_id="n1", ts=1_700_172_800, usd=D("0"), is_maker=False),
            fill(
                trade_id="n2",
                side="sell",
                ts=1_700_172_900,
                pnl=D("5"),
                usd=D("0"),
                is_maker=False,
                price=D("105"),
            ),
        ]
        trips = round_trips(rows, [], {}, {})
        self.assertEqual(len(trips), 3)
        one = summary(trips, "none")
        self.assertEqual(len(one), 1)
        stats = one[0]
        self.assertEqual(stats.count, 3)
        self.assertEqual(stats.wins, 2)
        self.assertEqual(stats.losses, 1)
        self.assertEqual(stats.win_rate, D("2") / D("3"))
        self.assertEqual(stats.gross_pnl, D("-15"))
        self.assertEqual(stats.net, D("-15"))
        self.assertEqual(stats.avg_win, D("7.5"))
        self.assertEqual(stats.avg_loss, D("-30"))
        self.assertEqual(stats.profit_factor, D("15") / D("30"))
        self.assertEqual(stats.expectancy, D("-5"))
        self.assertEqual(stats.largest_win, D("10"))
        self.assertEqual(stats.largest_loss, D("-30"))
        self.assertEqual(stats.maker_share, D("60") / D("80"))
        self.assertEqual([point.net for point in stats.curve], [D("10"), D("-20"), D("-15")])
        self.assertEqual(stats.max_drawdown, D("30"))
        # Edge without a plan: payoff 7.5/30, so it needs an 80% win rate to break even.
        self.assertEqual(stats.payoff_ratio, D("0.25"))
        self.assertEqual(stats.breakeven_win_rate, D("0.8"))
        self.assertEqual(stats.notional, D("80"))
        self.assertEqual(stats.net_bps, D("-15") / D("80") * 10_000)
        self.assertEqual(stats.recovery_factor, D("-0.5"))
        # W, L, W: no run longer than one; the last trip won.
        self.assertEqual(
            (stats.max_win_streak, stats.max_loss_streak, stats.current_streak), (1, 1, 1)
        )
        self.assertEqual(stats.avg_hold_win_s, D("100"))
        self.assertEqual(stats.avg_hold_loss_s, D("100"))
        assert stats.long is not None
        self.assertEqual((stats.long.count, stats.long.net), (3, D("-15")))
        self.assertIsNone(stats.short)
        self.assertEqual((stats.trading_days, stats.green_days), (3, 2))
        self.assertEqual((stats.best_day, stats.worst_day), (D("10"), D("-30")))
        self.assertEqual(stats.r_count, 0)

        only_win = summary(trips[:1], "none")[0]
        self.assertIsNone(only_win.profit_factor)
        self.assertIsNone(only_win.payoff_ratio)
        self.assertIsNone(only_win.breakeven_win_rate)
        self.assertEqual(summary(trips, "day")[0].key, "2023-11-14")
        self.assertEqual(len(summary(trips, "day")), 3)

    def test_streaks_run_in_close_order_and_skip_flat_trips(self) -> None:
        nets = ["5", "-1", "-2", "0", "-3", "4", "6"]
        rows: list[Fill] = []
        for i, net in enumerate(nets):
            t = 1_700_000_000 + i * 1000
            rows.append(fill(trade_id=f"o{i}", ts=t, usd=D("10")))
            rows.append(fill(trade_id=f"c{i}", side="sell", ts=t + 10, pnl=D(net), usd=D("10")))
        stats = summary(round_trips(rows, [], {}, {}), "none")[0]
        self.assertEqual(
            (stats.max_win_streak, stats.max_loss_streak, stats.current_streak), (2, 3, 2)
        )
