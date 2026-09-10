from decimal import Decimal
from unittest import TestCase

from mayedge.lighter.account import AccountService
from mayedge.lighter.models import OpenOrder, Position
from mayedge.lighter.parse import (
    apply_orders,
    desk_account_trade,
    merge_positions,
    parse_order,
    realized_close_pnl,
)
from mayedge.numbers import parse_decimal


def _pos(mi: int, symbol: str, size: str) -> Position:
    return Position(
        market_index=mi,
        symbol=symbol,
        size=size,
        entry_price="100",
        mark_price="100",
        unrealized_pnl="0",
        leverage=5,
        margin_mode="cross",
    )


def _order(mi: int, idx: int, remaining: str = "1", **extra: object) -> dict:
    row: dict = {
        "order_index": idx,
        "client_order_index": idx,
        "market_index": mi,
        "status": "open",
        "remaining_base_amount": remaining,
        "initial_base_amount": "1",
        "price": "100",
        "is_ask": False,
        "type": "limit",
        "reduce_only": False,
    }
    row.update(extra)
    return row


class ParseDecimalTests(TestCase):
    def test_comma_decimal(self) -> None:
        self.assertEqual(parse_decimal("0,5"), Decimal("0.5"))

    def test_grouped_dot_decimal(self) -> None:
        self.assertEqual(parse_decimal("1.234,56"), Decimal("1234.56"))

    def test_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_decimal("")


class MergePositionsTests(TestCase):
    def test_snapshot_replaces_missing_markets(self) -> None:
        existing = [_pos(1, "BTC", "1"), _pos(2, "ETH", "2")]
        raw = {1: {"market_id": 1, "symbol": "BTC", "position": "0.5"}}
        merged = merge_positions(existing, raw, snapshot=True)
        indices = {p.market_index for p in merged}
        self.assertEqual(indices, {1})
        self.assertEqual(merged[0].size, "0.5")

    def test_incremental_keeps_other_markets(self) -> None:
        existing = [_pos(1, "BTC", "1"), _pos(2, "ETH", "2")]
        raw = {1: {"market_id": 1, "symbol": "BTC", "position": "0.5"}}
        merged = merge_positions(existing, raw, snapshot=False)
        by_mi = {p.market_index: p for p in merged}
        self.assertEqual(set(by_mi), {1, 2})
        self.assertEqual(by_mi[1].size, "0.5")
        self.assertEqual(by_mi[2].size, "2")

    def test_incremental_empty_payload_keeps_existing(self) -> None:
        existing = [_pos(1, "BTC", "1"), _pos(2, "ETH", "2")]
        merged = merge_positions(existing, {}, snapshot=False)
        self.assertEqual({p.market_index for p in merged}, {1, 2})

    def test_incremental_zero_size_drops_that_market(self) -> None:
        existing = [_pos(1, "BTC", "1"), _pos(2, "ETH", "2")]
        raw = {1: {"market_id": 1, "symbol": "BTC", "position": "0"}}
        merged = merge_positions(existing, raw, snapshot=False)
        self.assertEqual({p.market_index for p in merged}, {2})


class ApplyOrdersTests(TestCase):
    def test_incremental_upsert_keeps_sibling_orders(self) -> None:
        existing = {
            1: [
                OpenOrder(1, 1, 1, "BTC", "buy", "100", "1", "1", "limit", False),
                OpenOrder(8, 8, 1, "BTC", "buy", "99", "1", "1", "limit", False),
            ],
            2: [OpenOrder(2, 2, 2, "ETH", "buy", "50", "1", "1", "limit", False)],
        }
        raw = {1: [_order(1, 9, remaining="0.4")]}
        merged = apply_orders(existing, raw, snapshot=False)
        self.assertEqual({o.order_index for o in merged[1]}, {1, 8, 9})
        self.assertEqual({o.order_index for o in merged[2]}, {2})

    def test_incremental_canceled_drops_only_that_order(self) -> None:
        existing = {
            1: [
                OpenOrder(1, 1, 1, "BTC", "buy", "100", "1", "1", "limit", False),
                OpenOrder(8, 8, 1, "BTC", "buy", "99", "1", "1", "limit", False),
            ],
        }
        raw = {1: [_order(1, 1, remaining="0", status="canceled")]}
        merged = apply_orders(existing, raw, snapshot=False)
        self.assertEqual({o.order_index for o in merged[1]}, {8})

    def test_incremental_amend_updates_price_in_place(self) -> None:
        existing = {
            1: [OpenOrder(1, 1, 1, "BTC", "buy", "100", "1", "1", "limit", False)],
        }
        raw = {1: [_order(1, 1, remaining="1", **{"price": "99.5"})]}
        merged = apply_orders(existing, raw, snapshot=False)
        self.assertEqual(len(merged[1]), 1)
        self.assertEqual(merged[1][0].price, "99.5")

    def test_incremental_empty_payload_keeps_existing(self) -> None:
        existing = {
            1: [OpenOrder(1, 1, 1, "BTC", "buy", "100", "1", "1", "limit", False)],
            2: [OpenOrder(2, 2, 2, "ETH", "buy", "50", "1", "1", "limit", False)],
        }
        merged = apply_orders(existing, {1: []}, snapshot=False)
        self.assertEqual({o.order_index for o in merged[1]}, {1})
        self.assertEqual({o.order_index for o in merged[2]}, {2})

    def test_snapshot_drops_unlisted_markets(self) -> None:
        existing = {
            1: [OpenOrder(1, 1, 1, "BTC", "buy", "100", "1", "1", "limit", False)],
            2: [OpenOrder(2, 2, 2, "ETH", "buy", "50", "1", "1", "limit", False)],
        }
        merged = apply_orders(existing, {2: [_order(2, 2)]}, snapshot=True)
        self.assertEqual(set(merged), {2})

    def test_list_payload_groups_by_market(self) -> None:
        existing: dict[int, list[OpenOrder]] = {}
        raw = [_order(1, 9), _order(2, 10)]
        merged = apply_orders(existing, raw, snapshot=True)
        self.assertEqual({o.order_index for o in merged[1]}, {9})
        self.assertEqual({o.order_index for o in merged[2]}, {10})

    def test_snapshot_list_does_not_wipe_when_misread_as_empty(self) -> None:
        # WS subscribe used to pass a list into apply_orders; non-dict became {}
        # and a snapshot then dropped REST-hydrated orders.
        existing = {
            1: [OpenOrder(1, 1, 1, "BTC", "buy", "100", "1", "1", "limit", False)],
        }
        merged = apply_orders(existing, [_order(1, 1), _order(1, 8)], snapshot=True)
        self.assertEqual({o.order_index for o in merged[1]}, {1, 8})

    def test_rest_wrapper_dict_with_orders_list(self) -> None:
        merged = apply_orders({}, {"code": 0, "orders": [_order(3, 11)]}, snapshot=True)
        self.assertEqual({o.order_index for o in merged[3]}, {11})


class ParseOrderTests(TestCase):
    def test_missing_remaining_uses_initial(self) -> None:
        parsed = parse_order(
            {
                "order_index": 1,
                "client_order_index": 1,
                "market_index": 3,
                "status": "open",
                "initial_base_amount": "2.5",
                "price": "10",
                "is_ask": True,
            }
        )
        assert parsed is not None
        self.assertEqual(parsed.remaining, "2.5")
        self.assertEqual(parsed.side, "sell")

    def test_remaining_from_initial_minus_filled(self) -> None:
        parsed = parse_order(
            {
                "order_index": 1,
                "client_order_index": 1,
                "market_index": 3,
                "status": "open",
                "initial_base_amount": "2.5",
                "filled_base_amount": "1.0",
                "price": "10",
                "is_ask": False,
            }
        )
        assert parsed is not None
        self.assertEqual(parsed.remaining, "1.5")
        self.assertEqual(parsed.filled, "1.0")


class DeskAccountTradeTests(TestCase):
    def test_rest_pnl_field(self) -> None:
        row = desk_account_trade(
            {
                "trade_id": 7,
                "market_id": 1,
                "size": "1",
                "price": "110",
                "bid_account_id": 9,
                "ask_account_id": 8,
                "is_maker_ask": True,
                "ask_account_pnl": "12.5",
                "bid_account_pnl": "0",
            },
            8,
        )
        assert row is not None
        self.assertEqual(row["side"], "sell")
        self.assertEqual(row["pnl"], "12.5")

    def test_ws_reconstruct_pnl_from_position_before(self) -> None:
        # Long 10 @ 100, sell 3 @ 110 → +30
        row = desk_account_trade(
            {
                "trade_id": 8,
                "market_id": 1,
                "size": "3",
                "price": "110",
                "bid_account_id": 1,
                "ask_account_id": 42,
                "is_maker_ask": True,
                "maker_position_size_before": "10",
                "maker_entry_quote_before": "1000",
            },
            42,
        )
        assert row is not None
        self.assertEqual(row["side"], "sell")
        self.assertAlmostEqual(float(row["pnl"]), 30.0)

    def test_add_to_position_has_zero_pnl(self) -> None:
        row = desk_account_trade(
            {
                "trade_id": 9,
                "market_id": 1,
                "size": "1",
                "price": "110",
                "bid_account_id": 42,
                "ask_account_id": 1,
                "is_maker_ask": False,
                "taker_position_size_before": "10",
                "taker_entry_quote_before": "1000",
            },
            42,
        )
        assert row is not None
        self.assertEqual(row["side"], "buy")
        self.assertAlmostEqual(float(row["pnl"]), 0.0)

    def test_realized_close_short(self) -> None:
        pnl = realized_close_pnl("-4", "400", "1", "90", is_buy=True)
        self.assertAlmostEqual(pnl, 10.0)


def _lighter_position(market_id: int, symbol: str, position: str) -> dict:
    """Venue Position JSON from the websocket reference."""
    return {
        "market_id": market_id,
        "symbol": symbol,
        "position": position,
        "sign": 1,
        "avg_entry_price": "100",
    }


class DeskAccountPositionsTests(TestCase):
    """Lighter account_all_positions frames → desk-visible account payload."""

    def setUp(self) -> None:
        self.svc = AccountService()

    def _desk_positions(self) -> dict[int, dict]:
        payload = self.svc.cached_account_payload()
        assert payload is not None
        return {int(p["market_index"]): p for p in payload["positions"]}

    def _feed_positions(self, positions: dict[int, dict], *, snapshot: bool) -> None:
        kind = "subscribed" if snapshot else "update"
        self.svc.handle_account_ws(
            {
                "type": f"{kind}/account_all_positions",
                "channel": "account_all_positions:1",
                "positions": positions,
            }
        )

    def _open_btc_and_eth(self) -> None:
        self._feed_positions(
            {
                1: _lighter_position(1, "BTC", "1"),
                2: _lighter_position(2, "ETH", "2"),
            },
            snapshot=True,
        )

    def test_snapshot_lists_every_open_market(self) -> None:
        self._feed_positions(
            {
                1: _lighter_position(1, "BTC", "0.5"),
                2: _lighter_position(2, "ETH", "2"),
            },
            snapshot=True,
        )
        by_mi = self._desk_positions()
        self.assertEqual(set(by_mi), {1, 2})
        self.assertEqual(by_mi[1]["size"], "0.5")
        self.assertEqual(by_mi[2]["size"], "2")

    def test_later_snapshot_is_the_whole_book(self) -> None:
        self._open_btc_and_eth()
        self._feed_positions({1: _lighter_position(1, "BTC", "0.5")}, snapshot=True)
        by_mi = self._desk_positions()
        self.assertEqual(set(by_mi), {1})
        self.assertEqual(by_mi[1]["size"], "0.5")

    def test_incremental_fill_on_one_market_leaves_the_others(self) -> None:
        self._open_btc_and_eth()
        self._feed_positions({1: _lighter_position(1, "BTC", "0.5")}, snapshot=False)
        by_mi = self._desk_positions()
        self.assertEqual(set(by_mi), {1, 2})
        self.assertEqual(by_mi[1]["size"], "0.5")
        self.assertEqual(by_mi[2]["size"], "2")

    def test_incremental_flat_closes_only_that_market(self) -> None:
        self._open_btc_and_eth()
        self._feed_positions({1: _lighter_position(1, "BTC", "0")}, snapshot=False)
        self.assertEqual(set(self._desk_positions()), {2})

    def test_empty_incremental_update_is_a_noop(self) -> None:
        self._open_btc_and_eth()
        self._feed_positions({}, snapshot=False)
        self.assertEqual(set(self._desk_positions()), {1, 2})

    def test_account_all_delta_does_not_replace_the_book(self) -> None:
        self._open_btc_and_eth()
        self.svc.handle_account_ws(
            {
                "type": "update/account_all",
                "channel": "account_all:1",
                "positions": {1: _lighter_position(1, "BTC", "0.1")},
            }
        )
        by_mi = self._desk_positions()
        self.assertEqual(set(by_mi), {1, 2})
        self.assertEqual(by_mi[1]["size"], "1")
        self.assertEqual(by_mi[2]["size"], "2")

    def test_positions_fe_type_is_the_same_channel(self) -> None:
        self.svc.handle_account_ws(
            {
                "type": "subscribed/account_all_positions_fe",
                "channel": "account_all_positions_fe/1",
                "positions": {1: _lighter_position(1, "BTC", "0.5")},
            }
        )
        by_mi = self._desk_positions()
        self.assertEqual(set(by_mi), {1})
        self.assertEqual(by_mi[1]["size"], "0.5")
