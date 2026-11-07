"""The alert rules in docs/alert-rules.md. Each test is named in the rule it pins."""

from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mayedge.alert_log import AlertLog, MemoryLogStore
from mayedge.alert_rows import order_away_pct
from mayedge.alerts import (
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


def _tape(
    step_pct: float = 0.1, vol: float = 300.0, minutes: int = 260, *, live: float = 1.0
) -> list[Candle]:
    """Closed bars up to _T0, the last at 100. Each steps ``step_pct`` from the one before.

    An odd span always moves ``step_pct``, so the Usual move is that on every span.
    ``live`` is the share of bars that traded.
    """
    out: list[Candle] = []
    for i in range(minutes):
        back = minutes - 1 - i
        px = 100.0 if back % 2 == 0 else 100.0 * (1 + step_pct / 100.0)
        traded = vol if (i * live) % 1 + live >= 1 else 0.0
        out.append(Candle(int(_T0) - (minutes - i) * 60, px, px, px, px, traded))
    return out


def _forming(vol: float, at: float = _T0) -> Candle:
    return Candle(int(at), 100.0, 100.0, 100.0, 100.0, vol)


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

    def market(self, mi: int = 1, *, step_pct: float = 0.1, vol: float = 300.0) -> None:
        """A market with 260 minutes behind it, its last close at 100."""
        self.det.seed_minute_bars(mi, _tape(step_pct, vol))
        self.seed(mi, [_snap(_T0 - 65)])

    def seed_board(self, markets: range, *, last: float) -> None:
        for mi in markets:
            self.det.seed_minute_bars(mi, _tape())
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
        # A closed Position is not held. A resting order with no price to measure is, with no side.
        self.assertEqual(held, {1: Held("short", 112.5), 2: Held()})

    def test_a_far_order_does_not_make_a_market_held(self) -> None:
        def order(market_index: int, side: str, price: str, trigger: str = "") -> OpenOrder:
            return OpenOrder(
                order_index=market_index,
                client_order_index=market_index,
                market_index=market_index,
                symbol=f"M{market_index}",
                side=side,
                price=price,
                size="1",
                remaining="1",
                order_type="stop_loss" if trigger else "limit",
                reduce_only=bool(trigger),
                trigger_price=trigger,
            )

        orders = [
            order(1, "buy", "90"),  # 10% under the last trade
            order(2, "buy", "98.5"),  # 1.5% under it
            order(3, "sell", "99"),  # already through
            order(4, "sell", "0", trigger="97"),  # a Stop 3% from mark
            order(5, "sell", "0", trigger="98.5"),  # a Stop 1.5% from mark
        ]
        gw = LighterGateway()
        for mi in range(1, 6):
            gw._markets[mi] = _meta(market_index=mi, symbol=f"M{mi}")
        with (
            patch.object(account_service, "list_open_orders", return_value=orders),
            patch.object(account_service.cached_summary(), "positions", []),
        ):
            held = gw._held_markets()
        self.assertEqual(sorted(held), [2, 3, 5])

    def test_order_away_is_measured_like_the_orders_tab(self) -> None:
        self.assertAlmostEqual(
            order_away_pct(side="buy", price=98.0, trigger=0.0, last=100.0, mark=101.0) or 0, 2.0
        )
        # No last trade: the limit is measured from mark.
        self.assertAlmostEqual(
            order_away_pct(side="sell", price=102.0, trigger=0.0, last=None, mark=100.0) or 0, 2.0
        )
        self.assertIsNone(order_away_pct(side="buy", price=98.0, trigger=0.0, last=None, mark=None))
        self.assertIsNone(
            order_away_pct(side="sell", price=0.0, trigger=97.0, last=100.0, mark=None)
        )


class ThresholdYamlTest(unittest.TestCase):
    def test_a_knob_overrides_its_default_and_no_other(self) -> None:
        thr = thresholds_from_dict({"move": {"x": 10, "floor_5m_pct": 2}})
        self.assertEqual((thr.move_x, thr.move_floor_5m_pct), (10.0, 2.0))
        self.assertEqual(thr.move_floor_1m_pct, AlertSettings().move_floor_1m_pct)

    def test_load_repo_yaml(self) -> None:
        thr = load_thresholds(Path(__file__).resolve().parents[1] / "config" / "alerts.yaml")
        self.assertEqual(thr, AlertSettings())


class GateTest(unittest.TestCase):
    def test_a_thin_market_never_alerts(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _tape())
        h.seed(1, [_snap(_T0 - 65, vol_quote=600_000.0)])
        self.assertEqual(h.tick(_at(102.0, volume_24h=600_000.0)), [])

    def test_a_thin_market_alerts_once_it_is_held(self) -> None:
        h = Harness()
        h.held[1] = Held(side="long")
        h.det.seed_minute_bars(1, _tape())
        h.seed(1, [_snap(_T0 - 65, vol_quote=600_000.0)])
        events = h.tick(_at(102.0, volume_24h=600_000.0))
        self.assertEqual([e["rule"] for e in events], ["move"])

    def test_a_dead_tape_never_alerts(self) -> None:
        # Half its minutes did not trade. A print 3% away is not a Move.
        h = Harness()
        h.det.seed_minute_bars(1, _tape(live=0.5))
        h.seed(1, [_snap(_T0 - 65)])
        self.assertEqual(h.tick(_at(103.0)), [])
        # Held, it is.
        h.held[1] = Held(side="short")
        self.assertEqual([e["rule"] for e in h.tick(_at(103.0), at=_T0 + 1)], ["move"])


class MoveTest(unittest.TestCase):
    def test_a_move_is_twelve_times_its_usual(self) -> None:
        # The usual minute moves 0.1%. 1.1% is eleven times it.
        h = Harness()
        h.market()
        self.assertEqual(h.tick(_at(101.1)), [])

        h = Harness()
        h.market()
        events = h.tick(_at(101.3))
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [("move", NOTABLE, "up")],
        )
        move = _fact(events, "move")
        self.assertEqual(move["window"], "1m")
        self.assertAlmostEqual(move["value"], 1.3)
        self.assertAlmostEqual(move["multiple"], 13.0, places=1)
        self.assertAlmostEqual(events[0]["size"], 1.3 / 1.2, places=2)

    def test_a_big_usual_needs_a_bigger_move(self) -> None:
        h = Harness()
        h.market(step_pct=0.5)
        self.assertEqual(h.tick(_at(103.0)), [])

    def test_a_small_move_on_a_still_tape_is_no_move(self) -> None:
        # Nothing moved, so anything is many times its usual. The floor decides.
        h = Harness()
        h.market(step_pct=0.0)
        self.assertEqual(h.tick(_at(100.9)), [])
        events = h.tick(_at(101.0), at=_T0 + 2)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(_fact(events, "move")["multiple"], 99.0)

    def test_a_move_is_judged_over_one_five_and_fifteen_minutes(self) -> None:
        # A grind: the last 15 closes climb from 100 to 102.2. No minute and no 5m is a Move.
        bars = _tape()
        for k in range(15):
            px = 100.0 + 2.2 * (k + 1) / 15
            t = bars[-15 + k].time
            bars[-15 + k] = Candle(t, px, px, px, px, 300.0)
        h = Harness()
        h.det.seed_minute_bars(1, bars)
        h.seed(1, [_snap(_T0 - 65)])
        events = h.tick(_at(102.4))
        self.assertEqual(_fact(events, "move")["window"], "15m")
        self.assertTrue(events[0]["note"].startswith("+2.25% in 15m · 23× its usual 15m"))

    def test_no_move_without_a_usual_behind_it(self) -> None:
        h = Harness()
        h.det.seed_minute_bars(1, _tape(minutes=200))
        h.seed(1, [_snap(_T0 - 65)])
        self.assertEqual(h.tick(_at(103.0)), [])

    def test_a_market_must_beat_the_board(self) -> None:
        h = Harness()
        h.seed_board(range(1, 13), last=101.0)
        h.det.seed_minute_bars(13, _tape())
        h.seed(13, [_snap(_T0 - 400)], "ZRO")
        self.assertEqual(h.tick(_at(101.3, market_index=13, symbol="ZRO")), [])

        h.det.seed_minute_bars(14, _tape())
        h.seed(14, [_snap(_T0 - 400)], "ENA")
        past_board = h.tick(_at(102.5, market_index=14, symbol="ENA"), at=_T0 + 2)
        self.assertEqual([e["market_index"] for e in past_board], [14])
        move = _fact(past_board, "move")
        self.assertAlmostEqual(move["value"], 2.5)
        self.assertAlmostEqual(move["excess"], 1.5)

    def test_a_move_that_keeps_going_is_one_row(self) -> None:
        h = Harness()
        h.market()
        first = h.tick(_at(101.3))
        self.assertEqual(len(first), 1)
        # Past the row's two minutes it is still the same Move, a little bigger.
        for second in range(130, 900, 60):
            self.assertEqual(h.tick(_at(101.5), at=_T0 + second), [])

    def test_a_move_that_grows_by_half_is_a_new_row(self) -> None:
        h = Harness()
        h.market()
        first = h.tick(_at(101.3))
        self.assertEqual(h.tick(_at(101.5), at=_T0 + 130), [])
        grown = h.tick(_at(102.0), at=_T0 + 140)
        self.assertEqual(len(grown), 1)
        self.assertNotEqual(grown[0]["id"], first[0]["id"])
        # Fifteen quiet minutes, and it starts afresh.
        h.tick(_at(100.0), at=_T0 + 150)
        fresh = h.tick(_at(101.3), at=_T0 + 150 + 901)
        self.assertEqual(len(fresh), 1)

    def test_a_move_says_its_volume_and_open_interest(self) -> None:
        # Each minute traded $30k. This one has traded $100k so far.
        h = Harness()
        h.market()
        h.det.seed_levels("oi", {1: [(_MINUTE - 1, 50_000_000.0)]})
        h.det.on_minute_bars(1, [_forming(1_000.0)])
        events = h.tick(_at(101.3, open_interest=50_500_000.0))
        self.assertEqual(_kinds(events), ["move", "volume", "oi"])
        self.assertAlmostEqual(_fact(events, "volume")["multiple"], 100_000.0 / 30_030.0, places=2)
        self.assertNotIn("size", _fact(events, "volume"))
        self.assertEqual(
            events[0]["note"],
            "+1.30% in 1m · 13× its usual 1m · volume 3× ($100k) · OI +1.00% (+$500k)",
        )

    def test_volume_alone_raises_nothing(self) -> None:
        h = Harness()
        h.market()
        h.det.on_minute_bars(1, [_forming(50_000.0)])
        self.assertEqual(h.tick(_at(100.05)), [])

    def test_open_interest_alone_raises_nothing(self) -> None:
        h = Harness()
        h.market()
        h.det.seed_levels("oi", {1: [(_MINUTE - 1, 50_000_000.0)]})
        self.assertEqual(h.tick(_at(100.05, open_interest=60_000_000.0)), [])


def _daily(
    days: int,
    *,
    high: float,
    low: float,
    now: float = _T0,
    recent_high: float | None = None,
) -> list[Candle]:
    """Completed UTC days before today. The most recent 7 can carry another high."""
    today = int(now) // 86_400 * 86_400
    out: list[Candle] = []
    for ago in range(days, 0, -1):
        bar_high = recent_high if recent_high is not None and ago <= 7 else high
        start = today - ago * 86_400
        out.append(Candle(start, low, bar_high, low, (bar_high + low) / 2, 1.0))
    return out


class WeekQuarterTest(unittest.TestCase):
    def _close(self, bars: list[Candle], close: float) -> tuple[Harness, list[dict[str, Any]]]:
        """The minute at _T0 closes at ``close``; the one before closed at 100."""
        h = Harness()
        h.market()
        h.det.seed_daily_bars(1, bars, _T0)
        h.det.on_minute_bars(1, [Candle(int(_T0), 100.0, close, 100.0, close, 300.0)])
        return h, h.tick(_at(close), at=_T0 + 61)

    def test_a_close_through_the_week_high_breaks_it(self) -> None:
        _h, events = self._close(_daily(7, high=100.1, low=90.0), 100.2)
        self.assertEqual(
            [(e["rule"], e["severity"], e["direction"]) for e in events],
            [("week_high", NOTABLE, "up")],
        )
        self.assertAlmostEqual(_fact(events, "week_high")["value"], 100.1)
        self.assertIn("through the week high 100.1", events[0]["note"])

        _h, down = self._close(_daily(7, high=110.0, low=99.9), 99.8)
        self.assertEqual(down[0]["rule"], "week_low")

    def test_touching_a_level_is_no_break(self) -> None:
        _h, events = self._close(_daily(7, high=100.2, low=90.0), 100.2)
        self.assertEqual(events, [])

    def test_a_close_through_the_quarter_high_breaks_it(self) -> None:
        # The quarter's high is older than the week. The week high is under both closes.
        bars = _daily(90, high=100.1, low=80.0, recent_high=99.0)
        _h, events = self._close(bars, 100.2)
        self.assertEqual(events[0]["rule"], "quarter_high")
        self.assertNotIn("week_high", _kinds(events))

    def test_a_level_breaks_once_a_day(self) -> None:
        h, first = self._close(_daily(7, high=100.1, low=90.0), 100.2)
        self.assertEqual(len(first), 1)
        h.det.on_minute_bars(1, [Candle(int(_T0) + 60, 100.2, 100.2, 100.0, 100.0, 300.0)])
        h.det.on_minute_bars(1, [Candle(int(_T0) + 120, 100.0, 100.2, 100.0, 100.2, 300.0)])
        self.assertEqual(h.tick(_at(100.2), at=_T0 + 181), [])

    def test_a_short_history_has_no_week_high(self) -> None:
        _h, events = self._close(_daily(6, high=100.1, low=90.0), 100.2)
        self.assertEqual(events, [])

    def test_today_is_not_part_of_the_week(self) -> None:
        today = int(_T0) // 86_400 * 86_400
        bars = [*_daily(7, high=100.1, low=90.0), Candle(today, 140.0, 150.0, 140.0, 149.0, 1.0)]
        # Today's 150 is not the week high. The completed week's 100.1 is.
        _h, events = self._close(bars, 100.2)
        self.assertEqual(events[0]["rule"], "week_high")
        self.assertAlmostEqual(_fact(events, "week_high")["value"], 100.1)


class LiquidationsTest(unittest.TestCase):
    def _liquidate(self, usd_each: float, n: int = 8, side: str = "sell") -> list[dict[str, Any]]:
        h = Harness()
        h.det.seed_minute_bars(1, _tape())
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
    def _line(self, h: Harness) -> dict[str, Any] | None:
        with patch("mayedge.alerts.time.time", return_value=_T0):
            return h.det.board_line()

    def test_a_board_move_is_counted_among_the_movers(self) -> None:
        # Twelve perps are up 0.9%. Eighteen sit flat, so the median of all thirty is zero.
        h = Harness()
        h.seed_board(range(1, 13), last=100.9)
        h.seed_board(range(13, 31), last=100.0)
        line = self._line(h)
        assert line is not None
        self.assertAlmostEqual(line["move_5m"], 0.9)
        self.assertEqual((line["same"], line["movers"], line["liquid"]), (12, 12, 30))

    def test_a_split_board_is_no_broad_move(self) -> None:
        few = Harness()
        few.seed_board(range(1, 9), last=101.0)
        few.seed_board(range(9, 15), last=99.0)
        self.assertIsNone(self._line(few))

        split = Harness()
        split.seed_board(range(1, 13), last=101.0)
        split.seed_board(range(13, 19), last=99.0)
        self.assertIsNone(self._line(split))

    def test_a_board_move_is_a_line_not_a_row(self) -> None:
        h = Harness()
        h.seed_board(range(1, 21), last=98.8)
        self.assertEqual(h.tick(_at(98.8, market_index=1)), [])
        line = self._line(h)
        assert line is not None
        self.assertEqual((line["direction"], line["same"]), ("down", 20))
        small = Harness()
        small.seed_board(range(1, 21), last=99.5)
        self.assertIsNone(self._line(small))


class HeldTest(unittest.TestCase):
    def _held(self, held: Held | None, price: float) -> list[dict[str, Any]]:
        h = Harness()
        if held is not None:
            h.held[1] = held
        h.market()
        return h.tick(_at(price))

    def test_a_move_against_a_held_side_is_urgent(self) -> None:
        self.assertEqual(self._held(None, 98.7)[0]["severity"], NOTABLE)
        events = self._held(Held(side="long"), 98.7)
        self.assertEqual(
            [(e["severity"], e["held"], e["direction"]) for e in events],
            [(URGENT, "long", "down")],
        )
        self.assertEqual(self._held(Held(side="short"), 101.3)[0]["severity"], URGENT)

    def test_a_move_with_a_held_side_is_notable(self) -> None:
        events = self._held(Held(side="long"), 101.3)
        self.assertEqual([(e["severity"], e["held"]) for e in events], [(NOTABLE, "long")])

    def test_a_move_near_a_working_order_is_urgent(self) -> None:
        events = self._held(Held(), 101.3)
        self.assertEqual([(e["severity"], e["held"]) for e in events], [(URGENT, "order")])

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
        second = book.ingest(1, "ETH", [_state("liqs", 2.0)], [], _T0 + 90, price=101.0)
        assert first is not None and second is not None
        self.assertEqual(second.id, first.id)
        self.assertEqual([f["kind"] for f in second.facts], ["liqs", "move"])
        self.assertEqual((second.rule, second.direction, second.price), ("liqs", "down", 100.0))

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
        later = book.ingest(1, "ETH", [_state("liqs", 1.1)], [], _T0 + 130, price=103.0)
        assert first is not None and later is not None
        self.assertNotEqual(later.id, first.id)
        self.assertEqual([f["kind"] for f in later.facts], ["liqs"])
        self.assertEqual((later.started_at, later.price), (later.ts, 103.0))

    def test_a_standing_state_is_one_row(self) -> None:
        book = self._book()
        self.assertIsNotNone(book.ingest(1, "ETH", [_state("liqs", 1.2)], [], _T0, price=100.0))
        for second in range(10, 900, 10):
            again = book.ingest(1, "ETH", [_state("liqs", 1.3)], [], _T0 + second, price=100.0)
            # It may grow on the row it opened. After that it has nothing new to say.
            self.assertTrue(again is None or second < 120)

    def test_a_state_that_grows_by_half_is_a_new_row(self) -> None:
        book = self._book()
        first = book.ingest(1, "ETH", [_state("liqs", 1.2)], [], _T0, price=100.0)
        self.assertIsNone(book.ingest(1, "ETH", [_state("liqs", 1.7)], [], _T0 + 150, price=100.0))
        grown = book.ingest(1, "ETH", [_state("liqs", 1.8)], [], _T0 + 160, price=100.0)
        assert first is not None and grown is not None
        self.assertNotEqual(grown.id, first.id)
        # Three minutes without firing, and it starts afresh at any size.
        fresh = book.ingest(1, "ETH", [_state("liqs", 1.0)], [], _T0 + 400, price=100.0)
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
    def test_a_row_carries_the_minute(self) -> None:
        h = Harness()
        h.market()
        h.held[1] = Held(side="long", liquidation_price=92.0)
        events = h.tick(_at(100.2))
        self.assertEqual(_kinds(events), ["near_liq", "move"])
        self.assertAlmostEqual(_fact(events, "move")["value"], 0.2)
        self.assertNotIn("size", _fact(events, "move"))

    def test_a_row_says_when_price_is_at_the_days_high(self) -> None:
        h = Harness()
        h.market()
        events = h.tick(_at(101.3, daily_price_high=101.3))
        self.assertEqual(_kinds(events), ["move", "day_high"])

        low = Harness()
        low.market()
        self.assertEqual(_kinds(low.tick(_at(98.7, daily_price_low=98.7))), ["move", "day_low"])

    def test_a_row_says_when_funding_is_extreme(self) -> None:
        h = Harness()
        h.market()
        h.det.seed_levels("funding", {1: [(_MINUTE - 40 + i, 0.001) for i in range(40)]})
        events = h.tick(_at(101.3, funding_rate=0.012))
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
