"""The alert rules in docs/alert-rules.md. Each test is named in the rule it pins."""

from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mayedge.alert_log import AlertLog, MemoryLogStore
from mayedge.alerts import (
    BROAD_INDEX,
    NOTABLE,
    URGENT,
    AlertDetector,
    AlertSettings,
    Fact,
    Held,
    MarketSnapshot,
    RowBook,
    load_thresholds,
    thresholds_from_dict,
)
from mayedge.lighter.account import account_service
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.models import Candle, MarketMeta, OpenOrder, Position, open_interest_usd

# On a minute boundary, so the forming bar opens at _T0.
_T0 = 1_800_000_000.0
_MINUTE = int(_T0) // 60


def _meta(**kwargs: object) -> MarketMeta:
    base: dict[str, object] = dict(
        market_index=1,
        symbol="ETH",
        price_decimals=2,
        size_decimals=4,
        min_base_amount=0.0,
        min_quote_amount=0.0,
        market_type="perp",
        volume_24h=10_000_000.0,
        mark_price=100.0,
        last_trade_price=100.0,
        mid_price=100.0,
        best_bid_price=99.99,
        best_ask_price=100.01,
        open_interest=50_000_000.0,
        daily_price_high=110.0,
        daily_price_low=90.0,
    )
    base.update(kwargs)
    return MarketMeta(**base)  # type: ignore[arg-type]


def _at(price: float, **kwargs: object) -> MarketMeta:
    return _meta(last_trade_price=price, mark_price=price, mid_price=price, **kwargs)


def _snap(ts: float, **kw: float) -> MarketSnapshot:
    row: dict[str, float] = dict(
        mark=100.0,
        last=100.0,
        index=100.0,
        mid=100.0,
        bid=99.99,
        ask=100.01,
        oi=50_000_000.0,
        vol_quote=10_000_000.0,
        funding=0.0,
        premium=0.0,
        day_high=110.0,
        day_low=90.0,
    )
    row.update(kw)
    return MarketSnapshot(ts=ts, **row)


def _hour(step_pct: float = 0.2, vol: float = 300.0, minutes: int = 70) -> list[Candle]:
    """Closed bars up to _T0. Each steps ``step_pct`` from the last and trades ``vol`` at 100."""
    out: list[Candle] = []
    for i in range(minutes):
        px = 100.0 * (1 + step_pct / 100.0) if i % 2 else 100.0
        out.append(Candle(int(_T0) - (minutes - i) * 60, px, px, px, px, vol))
    return out


def _forming(vol: float, at: float = _T0) -> Candle:
    return Candle(int(at), 100.0, 100.0, 100.0, 100.0, vol)


def _oi_hour(step_usd: float = 200_000.0, minutes: int = 70) -> list[tuple[int, float]]:
    return [
        (_MINUTE - (minutes - i), 50_000_000.0 + (step_usd if i % 2 else 0.0))
        for i in range(minutes)
    ]


class Harness:
    """A detector that never touches the desk database."""

    def __init__(self, thr: AlertSettings | None = None) -> None:
        self.messages: list[dict[str, Any]] = []
        self.store = MemoryLogStore()
        self.held: dict[int, Held] = {}
        self.det = AlertDetector(
            self.messages.append,
            thresholds=thr or AlertSettings(),
            log=AlertLog(store=self.store),
            held=lambda: self.held,
        )

    def seed(self, mi: int, snaps: list[MarketSnapshot], symbol: str = "") -> None:
        self.det._snapshots[mi] = deque(snaps, maxlen=400)
        self.det._symbols[mi] = symbol or f"M{mi}"

    def market(self, mi: int = 1, *, step_pct: float = 0.2, vol: float = 300.0) -> None:
        """A market with an hour behind it and a print from a minute ago."""
        self.det.seed_minute_bars(mi, _hour(step_pct, vol))
        self.seed(mi, [_snap(_T0 - 65)])

    def seed_board(self, markets: range, *, last: float) -> None:
        for mi in markets:
            self.seed(mi, [_snap(_T0 - 400), _snap(_T0 - 1, last=last, mark=last, mid=last)])

    def tick(self, meta: MarketMeta, at: float = _T0) -> list[dict[str, Any]]:
        before = len(self.messages)
        with patch("mayedge.alerts.time.time", return_value=at):
            self.det.on_market_stats(meta)
            self.det.flush()
        return [e for m in self.messages[before:] for e in m.get("events", [])]


def _fact(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(f for f in events[-1]["facts"] if f["kind"] == kind)


def _kinds(events: list[dict[str, Any]]) -> list[str]:
    return [f["kind"] for f in events[-1]["facts"]]


class ApplyMarketStatsTest(unittest.TestCase):
    def test_apply_market_stats_parses_extended_fields(self) -> None:
        gw = LighterGateway()
        gw._markets[1] = _meta()
        gw._apply_market_stats(
            {
                "market_stats": {
                    "market_id": 1,
                    "mark_price": "2000",
                    "open_interest": "5000000",
                    "best_bid_price": "1998",
                    "mid_price": "2000",
                }
            }
        )
        meta = gw._markets[1]
        self.assertEqual(meta.open_interest, 10_000_000.0)
        self.assertEqual(meta.best_bid_price, 1998.0)
        self.assertEqual(meta.mark_price, 2000.0)

    def test_open_interest_usd_matches_official_two_sided(self) -> None:
        self.assertEqual(open_interest_usd(54_100_000), 108_200_000)


class HeldMarketsTest(unittest.TestCase):
    def test_a_position_or_a_working_order_makes_a_market_held(self) -> None:
        def position(market_index: int, size: str, side: str, liq: str) -> Position:
            return Position(
                market_index=market_index,
                symbol=f"M{market_index}",
                size=size,
                entry_price="100",
                mark_price="100",
                unrealized_pnl="0",
                leverage=5,
                margin_mode="cross",
                liquidation_price=liq,
                side=side,
            )

        resting = OpenOrder(
            order_index=1,
            client_order_index=1,
            market_index=2,
            symbol="M2",
            side="buy",
            price="90",
            size="1",
            remaining="1",
            order_type="limit",
            reduce_only=False,
        )
        book = [position(1, "2", "short", "112.5"), position(3, "0", "long", "")]
        with (
            patch.object(account_service, "list_open_orders", return_value=[resting]),
            patch.object(account_service.cached_summary(), "positions", book),
        ):
            held = LighterGateway()._held_markets()
        # A closed Position is not held. A resting order is, with no side.
        self.assertEqual(held, {1: Held("short", 112.5), 2: Held()})


class ThresholdYamlTest(unittest.TestCase):
    def test_a_knob_overrides_its_default_and_no_other(self) -> None:
        thr = thresholds_from_dict({"spike": {"volume_x": 5, "window_min": 30}})
        self.assertEqual((thr.spike_volume_x, thr.spike_window_min), (5.0, 30))
        self.assertEqual(thr.spike_price_x, AlertSettings().spike_price_x)

    def test_load_repo_yaml(self) -> None:
        thr = load_thresholds(Path(__file__).resolve().parents[1] / "config" / "alerts.yaml")
        self.assertEqual(thr, AlertSettings())


class GateTest(unittest.TestCase):
    def test_a_thin_market_never_alerts(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _hour())
        h.seed(1, [_snap(_T0 - 65, vol_quote=600_000.0)])
        self.assertEqual(h.tick(_at(102.0, volume_24h=600_000.0)), [])

    def test_a_thin_market_alerts_once_it_is_held(self) -> None:
        h = Harness()
        h.held[1] = Held(side="long")
        h.det.seed_minute_bars(1, _hour())
        h.seed(1, [_snap(_T0 - 65, vol_quote=600_000.0)])
        events = h.tick(_at(102.0, volume_24h=600_000.0))
        self.assertEqual([e["rule"] for e in events], ["move"])


class PriceSpikeTest(unittest.TestCase):
    def test_a_price_spike_doubles_the_hours_biggest_minute(self) -> None:
        # The hour's biggest minute moved 0.2%. 0.35% is its biggest, and not twice it.
        h = Harness()
        h.market()
        self.assertEqual(h.tick(_at(100.35)), [])

        h = Harness()
        h.market()
        events = h.tick(_at(100.5))
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [
                ("move", NOTABLE, "up"),
            ],
        )
        move = _fact(events, "move")
        self.assertAlmostEqual(move["value"], 0.5)
        self.assertAlmostEqual(move["multiple"], 2.5, places=2)
        self.assertAlmostEqual(events[0]["size"], 1.25, places=2)

    def test_a_big_minute_in_a_wild_hour_is_no_spike(self) -> None:
        h = Harness()
        h.market(step_pct=0.5)
        self.assertEqual(h.tick(_at(100.7)), [])

    def test_a_small_move_on_a_dead_tape_is_no_spike(self) -> None:
        # Nothing moved all hour, so anything is many times the hour's biggest. The floor decides.
        h = Harness()
        h.market(step_pct=0.0)
        self.assertEqual(h.tick(_at(100.2)), [])
        self.assertEqual(len(h.tick(_at(100.3), at=_T0 + 2)), 1)

    def test_no_spike_without_an_hour_behind_it(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, [*_hour(minutes=30), _forming(5_000.0)])
        h.det.seed_levels("oi", {1: _oi_hour(minutes=30)})
        h.seed(1, [_snap(_T0 - 65)])
        self.assertEqual(h.tick(_at(102.0, open_interest=51_000_000.0)), [])

    def test_the_next_spike_has_to_beat_this_one(self) -> None:
        h = Harness()
        h.market()
        first = h.tick(_at(100.6))
        self.assertEqual(len(first), 1)
        # Its minute closes and becomes the hour's biggest.
        h.det.on_minute_bars(1, [Candle(int(_T0), 100.0, 100.6, 100.0, 100.6, 300.0)])
        self.assertEqual(h.tick(_at(100.6), at=_T0 + 70), [])
        self.assertEqual(h.tick(_at(100.6 * 1.006), at=_T0 + 140), [])
        bigger = h.tick(_at(100.6 * 1.006 * 1.013), at=_T0 + 210)
        self.assertEqual(len(bigger), 1)
        self.assertNotEqual(bigger[0]["id"], first[0]["id"])

    def test_a_market_must_beat_the_board(self) -> None:
        h = Harness()
        h.seed_board(range(1, 13), last=101.0)
        h.det.seed_minute_bars(13, _hour())
        h.seed(13, [_snap(_T0 - 400)], "ZRO")
        with_board = h.tick(_at(101.3, market_index=13, symbol="ZRO"))
        self.assertEqual({e["market_index"] for e in with_board}, {BROAD_INDEX})

        h.det.seed_minute_bars(14, _hour())
        h.seed(14, [_snap(_T0 - 400)], "ENA")
        past_board = h.tick(_at(102.5, market_index=14, symbol="ENA"), at=_T0 + 2)
        self.assertEqual([e["market_index"] for e in past_board], [14])
        move = _fact(past_board, "move")
        self.assertAlmostEqual(move["value"], 2.5)
        self.assertAlmostEqual(move["excess"], 1.5)


class VolumeSpikeTest(unittest.TestCase):
    def _trade(self, vol: float, price: float = 100.0) -> list[dict[str, Any]]:
        # Each minute of the hour traded $30k.
        h = Harness()
        h.market()
        h.det.on_minute_bars(1, [_forming(vol)])
        return h.tick(_at(price))

    def test_a_volume_spike_triples_the_hours_biggest_minute(self) -> None:
        # $80k is the hour's biggest minute, and not three times it.
        self.assertEqual(self._trade(800.0), [])
        events = self._trade(1_000.0)
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [
                ("volume", NOTABLE, "flat"),
            ],
        )
        volume = _fact(events, "volume")
        self.assertAlmostEqual(volume["value"], 100_000.0)
        self.assertAlmostEqual(volume["multiple"], 100_000.0 / 30_060.0, places=2)

    def test_a_quiet_hour_still_needs_real_money(self) -> None:
        h = Harness()
        h.market(vol=10.0)
        h.det.on_minute_bars(1, [_forming(400.0)])
        self.assertEqual(h.tick(_meta()), [])


class OiSpikeTest(unittest.TestCase):
    def _change(self, oi_now: float) -> list[dict[str, Any]]:
        # Each minute of the hour changed open interest by $200k.
        h = Harness()
        h.market()
        h.det.seed_levels("oi", {1: _oi_hour()})
        return h.tick(_meta(open_interest=oi_now))

    def test_an_oi_spike_doubles_the_hours_biggest_change(self) -> None:
        self.assertEqual(self._change(50_350_000.0), [])
        events = self._change(49_500_000.0)
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [
                ("oi", NOTABLE, "down"),
            ],
        )
        oi = _fact(events, "oi")
        self.assertAlmostEqual(oi["value"], -1.0)
        self.assertAlmostEqual(oi["usd"], -500_000.0)
        self.assertAlmostEqual(oi["multiple"], 2.5)

    def test_a_small_change_on_a_big_book_is_no_spike(self) -> None:
        # $300k is over the dollar floor and under 0.3% of a $200M book.
        h = Harness()
        h.market()
        h.seed(1, [_snap(_T0 - 65, oi=200_000_000.0)])
        h.det.seed_levels("oi", {1: [(m, 200_000_000.0) for m, _ in _oi_hour()]})
        self.assertEqual(h.tick(_meta(open_interest=200_300_000.0)), [])


class LiquidationsTest(unittest.TestCase):
    def _liquidate(self, usd_each: float, n: int = 8, side: str = "sell") -> list[dict[str, Any]]:
        h = Harness()
        h.seed(1, [_snap(_T0)], "ETH")
        items = [
            {
                "market_index": 1,
                "trade_id": f"1:liquidation:{i}",
                "usd_amount": str(usd_each),
                "side": side,
                "timestamp": int((_T0 - 8) * 1000),
            }
            for i in range(n)
        ]
        with patch("mayedge.alerts.time.time", return_value=_T0):
            h.det.on_liquidations(items)
        return [e for m in h.messages for e in m.get("events", [])]

    def test_liquidations_are_sized_against_open_interest(self) -> None:
        # $120k is 24 bps of $50M.
        events = self._liquidate(15_000.0)
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [
                ("liqs", URGENT, "down"),
            ],
        )
        self.assertAlmostEqual(_fact(events, "liqs")["bps"], 24.0)
        self.assertEqual(self._liquidate(15_000.0, side="buy")[0]["direction"], "up")
        self.assertEqual(self._liquidate(10_000.0), [])


class BoardTest(unittest.TestCase):
    def test_a_board_move_is_counted_among_the_movers(self) -> None:
        # Twelve perps are up 0.8%. Eighteen sit flat, so the median of all thirty is zero.
        h = Harness()
        h.seed_board(range(1, 13), last=100.8)
        h.seed_board(range(13, 31), last=100.0)
        events = h.tick(_meta(market_index=30, symbol="AAPL"))
        self.assertEqual([e["market_index"] for e in events], [BROAD_INDEX])
        board = _fact(events, "board")
        self.assertAlmostEqual(board["value"], 0.8)
        self.assertEqual(board["window"], "12/12")
        self.assertEqual(board["liquid"], 30)

    def test_a_split_board_is_no_broad_move(self) -> None:
        few = Harness()
        few.seed_board(range(1, 9), last=101.0)
        few.seed_board(range(9, 15), last=99.0)
        self.assertEqual(few.tick(_meta(market_index=20)), [])

        split = Harness()
        split.seed_board(range(1, 13), last=101.0)
        split.seed_board(range(13, 19), last=99.0)
        self.assertEqual(split.tick(_meta(market_index=20)), [])

    def test_a_board_move_is_one_row(self) -> None:
        h = Harness()
        h.seed_board(range(1, 21), last=98.8)
        events = h.tick(_at(98.8, market_index=1))
        self.assertEqual([(e["market_index"], e["symbol"]) for e in events], [(BROAD_INDEX, "BTC")])
        self.assertEqual((events[0]["severity"], events[0]["direction"]), (URGENT, "down"))
        self.assertIn("20/20 down", events[0]["note"])


class HeldTest(unittest.TestCase):
    def test_a_row_on_a_held_market_is_urgent(self) -> None:
        bystander = Harness()
        bystander.market()
        self.assertEqual(bystander.tick(_at(99.5))[0]["severity"], NOTABLE)

        h = Harness()
        h.held[1] = Held(side="long")
        h.market()
        events = h.tick(_at(99.5))
        self.assertEqual(
            [(e["severity"], e["held"], e["direction"]) for e in events],
            [
                (URGENT, "long", "down"),
            ],
        )

        resting = Harness()
        resting.held[1] = Held()
        resting.market()
        self.assertEqual(resting.tick(_at(99.5))[0]["held"], "order")

    def test_mark_near_the_liquidation_price(self) -> None:
        h = Harness()
        h.held[1] = Held(side="long", liquidation_price=92.0)
        h.seed(1, [_snap(_T0 - 65)])
        events = h.tick(_meta())
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [
                ("near_liq", URGENT, "down"),
            ],
        )
        self.assertAlmostEqual(_fact(events, "near_liq")["value"], 8.0)

        short = Harness()
        short.held[1] = Held(side="short", liquidation_price=104.0)
        short.seed(1, [_snap(_T0 - 65)])
        self.assertEqual(short.tick(_meta())[0]["direction"], "up")

        far = Harness()
        far.held[1] = Held(side="long", liquidation_price=80.0)
        far.seed(1, [_snap(_T0 - 65)])
        self.assertEqual(far.tick(_meta()), [])


def _spike(kind: str, size: float, direction: str = "up") -> Fact:
    return Fact(kind, direction, size, "pct", window="1m", size=size)


def _state(kind: str, size: float) -> Fact:
    return Fact(kind, "down", size, "pct", size=size)


class RowBookTest(unittest.TestCase):
    def _book(self, **kw: Any) -> RowBook:
        return RowBook(AlertSettings(max_new_per_min=50, **kw))

    def test_rules_within_two_minutes_are_one_row(self) -> None:
        book = self._book()
        first = book.ingest(1, "ETH", [_spike("move", 1.2)], [], _T0, price=100.0)
        second = book.ingest(1, "ETH", [_spike("oi", 2.0, "down")], [], _T0 + 90, price=101.0)
        assert first is not None and second is not None
        self.assertEqual(second.id, first.id)
        self.assertEqual([f["kind"] for f in second.facts], ["oi", "move"])
        self.assertEqual((second.rule, second.direction, second.price), ("oi", "down", 100.0))

    def test_an_unchanged_row_is_not_sent_again(self) -> None:
        book = self._book()
        self.assertIsNotNone(book.ingest(1, "ETH", [_spike("move", 1.2)], [], _T0, price=100.0))
        self.assertIsNone(book.ingest(1, "ETH", [_spike("move", 1.2)], [], _T0 + 1, price=100.0))
        self.assertIsNone(book.ingest(1, "ETH", [_spike("move", 1.1)], [], _T0 + 2, price=100.0))
        grown = book.ingest(1, "ETH", [_spike("move", 1.6)], [], _T0 + 3, price=100.0)
        assert grown is not None
        self.assertAlmostEqual(grown.size, 1.6)

    def test_a_final_row_is_not_rewritten(self) -> None:
        book = self._book()
        first = book.ingest(1, "ETH", [_spike("move", 1.2)], [], _T0, price=100.0)
        later = book.ingest(1, "ETH", [_spike("volume", 1.1, "flat")], [], _T0 + 130, price=103.0)
        assert first is not None and later is not None
        self.assertNotEqual(later.id, first.id)
        self.assertEqual([f["kind"] for f in later.facts], ["volume"])
        self.assertEqual((later.started_at, later.price), (later.ts, 103.0))

    def test_two_spikes_at_once_are_urgent(self) -> None:
        book = self._book()
        one = book.ingest(1, "ETH", [_spike("volume", 1.4, "flat")], [], _T0, price=100.0)
        two = book.ingest(1, "ETH", [_spike("move", 1.1)], [], _T0 + 20, price=100.0)
        assert one is not None and two is not None
        self.assertEqual((one.severity, one.direction), (NOTABLE, "flat"))
        # The volume spike is the larger rule. The row still points the way price went.
        self.assertEqual((two.severity, two.rule, two.direction), (URGENT, "volume", "up"))

    def test_a_standing_state_is_one_row(self) -> None:
        book = self._book()
        self.assertIsNotNone(book.ingest(-1, "BTC", [_state("board", 1.2)], [], _T0, price=0.0))
        for second in range(10, 900, 10):
            again = book.ingest(-1, "BTC", [_state("board", 1.3)], [], _T0 + second, price=0.0)
            # It may grow on the row it opened. After that it has nothing new to say.
            self.assertTrue(again is None or second < 120)

    def test_a_state_that_grows_by_half_is_a_new_row(self) -> None:
        book = self._book()
        first = book.ingest(-1, "BTC", [_state("board", 1.2)], [], _T0, price=0.0)
        self.assertIsNone(book.ingest(-1, "BTC", [_state("board", 1.7)], [], _T0 + 150, price=0.0))
        grown = book.ingest(-1, "BTC", [_state("board", 1.8)], [], _T0 + 160, price=0.0)
        assert first is not None and grown is not None
        self.assertNotEqual(grown.id, first.id)
        # Three minutes without firing, and it starts afresh at any size.
        fresh = book.ingest(-1, "BTC", [_state("board", 1.0)], [], _T0 + 400, price=0.0)
        assert fresh is not None
        self.assertNotEqual(fresh.id, grown.id)

    def test_rate_cap(self) -> None:
        book = RowBook(AlertSettings(max_new_per_min=2))
        opened = [
            book.ingest(mi, f"M{mi}", [_spike("move", 1.2)], [], _T0, price=100.0)
            for mi in range(1, 5)
        ]
        self.assertEqual(sum(ev is not None for ev in opened), 2)


class TapeTest(unittest.TestCase):
    def test_a_row_carries_what_the_tape_showed(self) -> None:
        # Price spiked. Volume was the hour's biggest minute and no more: shown, not a rule.
        h = Harness()
        h.market()
        h.det.on_minute_bars(1, [_forming(800.0)])
        events = h.tick(_at(100.5))
        self.assertEqual(_kinds(events), ["move", "volume"])
        self.assertEqual((events[0]["rule"], events[0]["severity"]), ("move", NOTABLE))
        self.assertNotIn("size", _fact(events, "volume"))
        self.assertEqual(
            events[0]["note"], "+0.50% 1m · 2.5× hour max · Vol $80k 1m · 2.7× hour max"
        )

        # Volume spiked and price did not. The row still says what price did.
        flat = Harness()
        flat.market()
        flat.det.on_minute_bars(1, [_forming(1_000.0)])
        events = flat.tick(_at(100.04))
        self.assertEqual(_kinds(events), ["volume", "move"])
        self.assertAlmostEqual(_fact(events, "move")["value"], 0.04)
        self.assertNotIn("size", _fact(events, "move"))

    def test_a_row_says_when_price_is_at_the_days_high(self) -> None:
        h = Harness()
        h.market()
        events = h.tick(_at(100.5, daily_price_high=100.5))
        self.assertEqual(_kinds(events), ["move", "day_high"])

        low = Harness()
        low.market()
        self.assertEqual(_kinds(low.tick(_at(99.5, daily_price_low=99.51))), ["move", "day_low"])

    def test_a_row_says_when_funding_is_extreme(self) -> None:
        h = Harness()
        h.market()
        h.det.seed_levels("funding", {1: [(_MINUTE - 40 + i, 0.001) for i in range(40)]})
        events = h.tick(_at(100.5, funding_rate=0.012))
        self.assertEqual(_kinds(events), ["move", "funding"])
        self.assertAlmostEqual(_fact(events, "funding")["z"], 5.5)


class FundingStripTest(unittest.TestCase):
    def _strip(self, funding_now: float) -> list[dict[str, Any]]:
        h = Harness()
        h.held[3] = Held(side="short")
        day = [(_MINUTE - 40 + i, 0.001) for i in range(40)]
        h.det.seed_levels("funding", {1: day, 2: day, 3: day})
        h.seed(1, [_snap(_T0 - 1, funding=funding_now)], "ETH")
        h.seed(2, [_snap(_T0 - 1, funding=-0.02, vol_quote=600_000.0)], "THIN")
        h.seed(3, [_snap(_T0 - 1, funding=-0.02, vol_quote=600_000.0)], "MINE")
        h.seed(4, [_snap(_T0 - 1, funding=0.05)], "NEW")
        with patch("mayedge.alerts.time.time", return_value=_T0):
            return h.det.funding_extremes()

    def test_funding_far_from_its_own_day_is_extreme(self) -> None:
        # The day sat at 0.001. Three sigma at the floor is 0.006 away.
        self.assertNotIn("ETH", [row["symbol"] for row in self._strip(0.006)])
        (eth,) = [row for row in self._strip(0.008) if row["symbol"] == "ETH"]
        self.assertEqual((eth["funding"], eth["z"]), (0.008, 3.5))

    def test_the_strip_lists_what_is_extreme_now(self) -> None:
        # Furthest first. A thin market is on it only when held. A market with no day is not.
        rows = self._strip(0.008)
        self.assertEqual(
            [(row["symbol"], row["held"]) for row in rows],
            [
                ("MINE", True),
                ("ETH", False),
            ],
        )


class ActivityTest(unittest.TestCase):
    def _board(self) -> list[dict[str, Any]]:
        h = Harness()
        h.held[2] = Held(side="short")
        h.seed(1, [_snap(_T0 - 400), _snap(_T0 - 1, last=101.0, oi=50_500_000.0)], "ETH")
        h.seed(2, [_snap(_T0 - 1, funding=0.004)], "BTC")
        h.seed(3, [_snap(_T0 - 1, vol_quote=600_000.0)], "THIN")
        with patch("mayedge.alerts.time.time", return_value=_T0):
            return h.det.activity()

    def test_activity_lists_every_liquid_perp(self) -> None:
        rows = self._board()
        self.assertEqual([row["symbol"] for row in rows], ["BTC", "ETH"])
        eth = rows[1]
        self.assertAlmostEqual(eth["move_5m"], 1.0)
        # The day ranged 90 to 110.
        self.assertAlmostEqual(eth["share"], 1.0 / (20.0 / 90.0 * 100.0))
        self.assertAlmostEqual(eth["oi_5m"], 1.0)
        self.assertAlmostEqual(eth["oi_usd_5m"], 500_000.0)
        # No bars and no history yet: blank, not zero.
        self.assertIsNone(eth["vol_x"])
        self.assertIsNone(eth["funding_z"])
        self.assertEqual(
            (rows[0]["funding"], rows[0]["held"], rows[0]["move_5m"]), (0.004, True, None)
        )

    def test_a_thin_market_is_on_no_board(self) -> None:
        self.assertNotIn("THIN", [row["symbol"] for row in self._board()])


if __name__ == "__main__":
    unittest.main()
