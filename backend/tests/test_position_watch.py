"""docs/position-rules.md: the Position watch."""

from __future__ import annotations

import asyncio
import calendar
import unittest
from pathlib import Path
from typing import Any

import yaml

from mayedge.position_watch import (
    Held,
    IdeaStop,
    Look,
    PositionWatch,
    PositionWatchLoop,
    StopOrder,
    WatchSettings,
    r_multiple,
    stop_price,
)
from mayedge.push_router import PushRouter
from mayedge.push_settings import PushSettings, push_settings_from_dict

# 6 Nov 2026 12:00 UTC: past the 07:00 brief.
NOON = float(calendar.timegm((2026, 11, 6, 12, 0, 0)))
# 6 Nov 2026 06:00 UTC: before it.
DAWN = float(calendar.timegm((2026, 11, 6, 6, 0, 0)))


def _eth(mark: float = 2_000.0, **kw: Any) -> Held:
    base: dict[str, Any] = dict(
        market_index=0,
        symbol="ETH",
        side="long",
        size=1.0,
        entry=2_000.0,
        mark=mark,
        trip="0:1",
    )
    base.update(kw)
    return Held(**base)


def _stopped(*positions: Held, stop: float = 1_900.0) -> Look:
    """Each Position with a Stop, so No stop stays out of the way."""
    stops = [
        StopOrder(p.market_index, "sell" if p.side == "long" else "buy", stop) for p in positions
    ]
    return Look(positions=list(positions), stops=stops)


def _quiet() -> PositionWatch:
    """No brief, so only the event under test pushes."""
    return PositionWatch(WatchSettings(brief_at=""))


def _keys(pushes: list[Any]) -> list[str]:
    return [p.key for p in pushes]


class ReadTest(unittest.TestCase):
    def test_a_tick_reads_only_what_it_is_given(self) -> None:
        sent: list[dict[str, Any]] = []

        async def gather() -> Look:
            return Look(positions=[_eth()])

        watch = PositionWatch(WatchSettings(no_stop_after_s=0, brief_at=""))
        loop = PositionWatchLoop(gather, sent.append, watch)
        self.assertEqual(asyncio.run(loop.tick()), 1)
        self.assertEqual(sent[0]["type"], "position_watch")
        self.assertEqual(sent[0]["key"], "position:nostop:0")
        self.assertFalse(sent[0]["urgent"])

    def test_a_flat_position_forgets_its_round_trip(self) -> None:
        w = _quiet()
        w.look(_stopped(_eth()), NOON)
        self.assertEqual(_keys(w.look(_stopped(_eth(2_100.0)), NOON)), ["position:0:1:r1"])
        w.look(Look(), NOON)
        # The same Round trip key after flat is a fresh Round trip: 1R is news again.
        w.look(_stopped(_eth()), NOON)
        self.assertEqual(_keys(w.look(_stopped(_eth(2_100.0)), NOON)), ["position:0:1:r1"])

    def test_what_is_already_true_at_boot_is_not_sent(self) -> None:
        w = _quiet()
        ideas = [IdeaStop("ETH", "long", 1_900.0)]
        boot = _stopped(_eth(2_150.0, funding=-50.0))
        boot.ideas = ideas
        boot.closes = {0: 1_890.0}
        boot.crowded = {0: (0.04, 4.0)}
        self.assertEqual(w.look(boot, NOON), [])
        # Still true a tick later: nothing new to say.
        self.assertEqual(w.look(boot, NOON + 10), [])

    def test_a_round_trip_opened_later_is_told(self) -> None:
        w = _quiet()
        w.look(Look(), NOON)
        late = _stopped(_eth(2_000.0))
        late.ideas = [IdeaStop("ETH", "long", 1_900.0)]
        late.closes = {0: 1_890.0}
        pushes = w.look(late, NOON)
        self.assertEqual(_keys(pushes), ["position:0:1:thesis"])
        self.assertTrue(pushes[0].urgent)


class StopTest(unittest.TestCase):
    def test_a_stop_order_or_a_planner_protects(self) -> None:
        w = PositionWatch(WatchSettings(no_stop_after_s=0, brief_at=""))
        self.assertEqual(w.look(_stopped(_eth()), NOON), [])
        guarded = Look(positions=[_eth()], guarded={0})
        self.assertEqual(w.look(guarded, NOON), [])
        # A buy Stop does not close a long.
        wrong = Look(positions=[_eth()], stops=[StopOrder(0, "buy", 1_900.0)])
        self.assertEqual(_keys(w.look(wrong, NOON)), ["position:nostop:0"])

    def test_the_nearest_stop_is_the_stop_price(self) -> None:
        pos = _eth(2_000.0)
        stops = [StopOrder(0, "sell", 1_800.0), StopOrder(0, "sell", 1_950.0)]
        self.assertEqual(stop_price(pos, stops), 1_950.0)
        self.assertIsNone(stop_price(pos, [StopOrder(1, "sell", 1_950.0)]))

    def test_the_idea_stop_is_the_plan_stop(self) -> None:
        w = _quiet()
        look = _stopped(_eth(), stop=1_950.0)
        look.ideas = [IdeaStop("ETH", "long", 1_900.0, 1), IdeaStop("ETH", "short", 2_200.0, 2)]
        w.look(look, NOON)
        # 1R from the Idea's 100, not the Stop's 50.
        up = _stopped(_eth(2_060.0), stop=1_950.0)
        up.ideas = look.ideas
        self.assertEqual(w.look(up, NOON), [])
        up = _stopped(_eth(2_100.0), stop=1_950.0)
        up.ideas = look.ideas
        self.assertEqual(_keys(w.look(up, NOON)), ["position:0:1:r1"])

    def test_a_moved_stop_does_not_move_r(self) -> None:
        w = _quiet()
        w.look(_stopped(_eth(), stop=1_900.0), NOON)
        # The Stop is trailed to 1,990. R is still measured from 1,900.
        pushes = w.look(_stopped(_eth(2_100.0), stop=1_990.0), NOON)
        self.assertEqual(_keys(pushes), ["position:0:1:r1"])
        self.assertIn("+1.0R", pushes[0].text)

    def test_r_is_the_move_over_the_risk(self) -> None:
        self.assertAlmostEqual(r_multiple(_eth(2_150.0), 1_900.0) or 0, 1.5)
        self.assertAlmostEqual(r_multiple(_eth(1_950.0), 1_900.0) or 0, -0.5)
        short = _eth(1_900.0, side="short")
        self.assertAlmostEqual(r_multiple(short, 2_100.0) or 0, 1.0)
        self.assertIsNone(r_multiple(_eth(), None))
        self.assertIsNone(r_multiple(_eth(), 2_000.0))


class EventTest(unittest.TestCase):
    def test_no_stop_waits_then_names_every_bare_position(self) -> None:
        w = PositionWatch(WatchSettings(no_stop_after_s=300, brief_at=""))
        lit = Held(120, "LIT", "long", 1_000.0, 3.4, 3.39, trip="120:1")
        look = Look(positions=[_eth(), lit])
        self.assertEqual(w.look(look, NOON), [])
        pushes = w.look(look, NOON + 300)
        self.assertEqual(_keys(pushes), ["position:nostop:0-120"])
        self.assertEqual(pushes[0].text, "⚠️ No stop on 2 Positions: LIT long 1,000, ETH long 1")
        # Nothing joined: quiet.
        self.assertEqual(w.look(look, NOON + 400), [])
        # ETH gets a Stop and loses it again: it joins again after the wait.
        w.look(Look(positions=[_eth(), lit], stops=[StopOrder(0, "sell", 1_900.0)]), NOON + 500)
        self.assertEqual(w.look(look, NOON + 600), [])
        self.assertEqual(_keys(w.look(look, NOON + 900)), ["position:nostop:0-120"])

    def test_halfway_to_the_stop(self) -> None:
        w = _quiet()
        w.look(_stopped(_eth()), NOON)
        pushes = w.look(_stopped(_eth(1_950.0)), NOON)
        self.assertEqual(_keys(pushes), ["position:0:1:r-0.5"])
        self.assertEqual(
            pushes[0].text, "ETH long: halfway to the stop, −0.5R (mark 1,950, stop 1,900)"
        )
        self.assertEqual(w.look(_stopped(_eth(1_940.0)), NOON), [])

    def test_two_levels_at_once_send_the_higher(self) -> None:
        w = _quiet()
        w.look(_stopped(_eth()), NOON)
        pushes = w.look(_stopped(_eth(2_250.0)), NOON)
        self.assertEqual(_keys(pushes), ["position:0:1:r2"])
        self.assertEqual(pushes[0].text, "ETH long: +2.5R (mark 2,250, entry 2,000)")

    def test_crowded_once_a_day_when_the_side_pays(self) -> None:
        w = _quiet()
        w.look(_stopped(_eth()), NOON)
        shorts_pay = _stopped(_eth())
        shorts_pay.crowded = {0: (-0.03, -3.5)}
        self.assertEqual(w.look(shorts_pay, NOON), [])
        longs_pay = _stopped(_eth())
        longs_pay.crowded = {0: (0.042, 4.1)}
        pushes = w.look(longs_pay, NOON)
        self.assertEqual(_keys(pushes), ["position:0:1:crowded:2026-11-06"])
        self.assertEqual(
            pushes[0].text,
            "ETH long: crowded, funding +0.0420%/h is 4.1σ from its day, and longs pay",
        )
        self.assertEqual(w.look(longs_pay, NOON + 3_600), [])
        self.assertEqual(len(w.look(longs_pay, NOON + 86_400)), 1)

    def test_funding_bleed_is_a_share_of_r(self) -> None:
        w = _quiet()
        w.look(_stopped(_eth(funding=-10.0)), NOON)
        # R in dollars is 100 × 1. A quarter of it is $25.
        self.assertEqual(w.look(_stopped(_eth(funding=-24.0)), NOON), [])
        pushes = w.look(_stopped(_eth(funding=-30.0)), NOON)
        self.assertEqual(_keys(pushes), ["position:0:1:bleed"])
        self.assertEqual(pushes[0].text, "ETH long: funding has cost $30, 0.3R of its $100 risk")

    def test_the_brief_goes_once_a_day_after_its_time(self) -> None:
        w = PositionWatch(WatchSettings(brief_at="07:00", no_stop_after_s=10**9))
        lit = Held(120, "LIT", "long", 1_000.0, 3.4, 3.39, liq=3.0, trip="120:1", funding=-0.3)
        look = Look(
            positions=[lit, _eth(1_950.0, funding=-1.0)],
            stops=[StopOrder(0, "sell", 1_900.0)],
        )
        self.assertEqual(w.look(look, DAWN), [])
        pushes = w.look(look, NOON)
        self.assertEqual(_keys(pushes), ["position:brief:2026-11-06"])
        self.assertEqual(
            pushes[0].text,
            "Positions, 07:00 UTC\n"
            "LIT long 1,000 · −$10 · no stop · liq 12% away · funding $0\n"
            "ETH long 1 · −$50 · −0.5R · stop 2.6% away · funding −$1",
        )
        self.assertEqual(w.look(look, NOON + 60), [])


class PushTest(unittest.TestCase):
    class _Sink:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str, bool]] = []

        def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None:
            self.sent.append((key, text, urgent))

    class _Clock:
        def now(self) -> float:
            return NOON

        def mono(self) -> float:
            return 0.0

        async def sleep(self, seconds: float) -> None:
            return None

    def test_the_router_sends_it_unless_positions_is_off(self) -> None:
        msg = {"type": "position_watch", "key": "position:0:1:thesis", "text": "t", "urgent": True}
        sink = self._Sink()
        PushRouter(sink, PushSettings(), self._Clock()).on_message(msg)
        self.assertEqual(sink.sent, [("position:0:1:thesis", "t", True)])
        off = self._Sink()
        PushRouter(off, PushSettings(positions="off"), self._Clock()).on_message(msg)
        self.assertEqual(off.sent, [])

    def test_the_knobs_read_from_yaml(self) -> None:
        cfg = push_settings_from_dict({"push": {"positions": False, "brief_at": ""}})
        self.assertEqual((cfg.positions, cfg.brief_at), ("off", ""))
        self.assertEqual(push_settings_from_dict({}).brief_at, "07:00")
        repo = Path(__file__).resolve().parents[1] / "config" / "alerts.yaml"
        cfg = push_settings_from_dict(yaml.safe_load(repo.read_text()))
        self.assertEqual(
            (cfg.positions, cfg.no_stop_after_s, cfg.bleed_r, cfg.brief_at),
            ("on", 300, 0.25, "07:00"),
        )


if __name__ == "__main__":
    unittest.main()


class FeedTest(unittest.TestCase):
    def test_gather_reads_the_desk_and_the_journal(self) -> None:
        from unittest.mock import AsyncMock, patch

        from mayedge import position_watch_feed as feed
        from mayedge.lighter.models import Candle, OpenOrder, Position

        pos = Position(
            market_index=0,
            symbol="ETH",
            size="0.5",
            entry_price="2000",
            mark_price="1990",
            unrealized_pnl="-5",
            leverage=5,
            margin_mode="cross",
            liquidation_price="0",
            side="long",
        )
        stop = OpenOrder(
            order_index=1,
            client_order_index=1,
            market_index=0,
            symbol="ETH",
            side="sell",
            price="0",
            size="0.5",
            remaining="0.5",
            order_type="stop_loss",
            reduce_only=True,
            trigger_price="1900",
        )
        ticket = OpenOrder(
            order_index=2,
            client_order_index=2,
            market_index=0,
            symbol="ETH",
            side="sell",
            price="2300",
            size="0.5",
            remaining="0.5",
            order_type="limit",
            reduce_only=False,
        )
        hour = int(NOON) // 3_600 * 3_600
        bars = [
            Candle(hour - 7_200, 1, 1, 1, 1_950.0, 1),
            Candle(hour - 3_600, 1, 1, 1, 1_890.0, 1),
            Candle(hour, 1, 1, 1, 1_995.0, 1),  # still forming
        ]
        summary = feed.account_service.cached_summary()
        journal = {
            "positions": [
                {"market_index": 0, "side": "long", "trip_key": "0:77", "funding": "-1.5"}
            ]
        }
        algos = {
            "working": [
                {"market_index": 6, "algo_type": "trail", "status": "running"},
                {"market_index": 24, "algo_type": "ladder", "status": "running"},
            ]
        }
        ideas = [{"symbol": "ETH", "side": "long", "stop": "1900", "updated_at": 5}]
        feed._closes.clear()
        with (
            patch.object(summary, "positions", [pos]),
            patch.object(feed.account_service, "list_open_orders", return_value=[stop, ticket]),
            patch.object(feed.gateway, "get_market_by_index", return_value=None),
            patch.object(feed.gateway, "funding_extremes", return_value=[]),
            patch.object(feed.gateway, "get_candles", AsyncMock(return_value=bars)) as candles,
            patch.object(feed.desk, "algo_book", return_value=algos),
            patch.object(feed, "ideas_list", return_value=ideas),
            patch("mayedge.api.routes.journal.last_open", return_value=journal),
            patch.object(feed.time, "time", return_value=NOON),
        ):
            look = asyncio.run(feed.gather())
            asyncio.run(feed.gather())
        self.assertEqual(
            look.positions,
            [Held(0, "ETH", "long", 0.5, 2_000.0, 1_990.0, 0.0, "0:77", -1.5)],
        )
        self.assertEqual(look.stops, [StopOrder(0, "sell", 1_900.0)])
        self.assertEqual(look.guarded, {6})
        self.assertEqual(look.ideas, [IdeaStop("ETH", "long", 1_900.0, 5)])
        # The last closed bar, not the forming one, read once for the hour.
        self.assertEqual(look.closes, {0: 1_890.0})
        self.assertEqual(candles.await_count, 1)
