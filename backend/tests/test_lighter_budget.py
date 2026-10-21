"""Shared Standard-tier budget, nonce retry, and the order paths that use them."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from expect_logs import expects_logs
from pydantic import ValidationError

from mayedge.algos.chase.job import ChaseIcebergRunner
from mayedge.algos.ladder.job import LadderRunner
from mayedge.api.schemas import TwapOrderRequest
from mayedge.lighter.budget import CAP, KILL_LANE, TX_CAP, TX_CEILING, BudgetRefused, budget
from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.market_ws import SendPacer, handle_ws_message
from mayedge.lighter.models import MarketMeta
from mayedge.lighter.order_book import OrderBookFeed
from mayedge.lighter.orders import OrderService


class BudgetTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        budget.reset()

    def tearDown(self) -> None:
        budget.reset()

    def test_class_ceilings_leave_room_for_manual_orders(self) -> None:
        for _ in range(40):
            self.assertTrue(budget.try_acquire(lane="critical"))
        self.assertFalse(budget.try_acquire(lane="read"))
        self.assertFalse(budget.try_acquire(lane="background"))
        self.assertTrue(budget.try_acquire(lane="algo"))
        for _ in range(3):
            self.assertTrue(budget.try_acquire(lane="critical"))
        self.assertFalse(budget.try_acquire(lane="algo"))
        self.assertTrue(budget.try_acquire(lane="critical"))
        self.assertFalse(budget.cooling())

    def test_sendtx_cap_is_separate_from_reads(self) -> None:
        for _ in range(TX_CAP):
            self.assertTrue(budget.try_acquire(lane="critical", tx=True))
        self.assertFalse(budget.try_acquire(lane="critical", tx=True))
        self.assertTrue(budget.try_acquire(lane="critical"))

    @expects_logs()
    def test_venue_block_cools_every_lane(self) -> None:
        budget.note_blocked()
        self.assertFalse(budget.try_acquire(lane="critical"))
        self.assertTrue(budget.cooling())

    async def test_background_waits_for_a_free_slot(self) -> None:
        now = time.monotonic()
        budget._hits = [(now - 59.8, False) for _ in range(25)]
        started = time.monotonic()
        await asyncio.wait_for(budget.take("background", wait=True), timeout=2)
        self.assertGreaterEqual(time.monotonic() - started, 0.15)
        self.assertLessEqual(len(budget._hits), 26)

    def test_cap_constant_stays_under_the_venue_bucket(self) -> None:
        self.assertLessEqual(CAP, 54)
        self.assertLessEqual(TX_CAP, 38)

    def test_snapshot_counts_the_window_and_rolls_it_off(self) -> None:
        now = time.monotonic()
        budget._hits = [(now, True), (now, False), (now - 61, True)]
        snap = budget.snapshot()
        self.assertEqual(snap["requests"], 2)
        self.assertEqual(snap["tx"], 1)
        self.assertEqual(snap["requests_cap"], CAP)
        self.assertEqual(snap["tx_cap"], TX_CAP)
        self.assertEqual(snap["algo_tx_cap"], TX_CEILING["algo"])
        budget._hits = [(now - 61, True), (now - 61, False)]
        rolled = budget.snapshot()
        self.assertEqual(rolled["requests"], 0)
        self.assertEqual(rolled["tx"], 0)

    async def test_a_local_refusal_counts_for_a_minute(self) -> None:
        for _ in range(CAP):
            self.assertTrue(budget.try_acquire(lane="critical"))
        with self.assertRaises(BudgetRefused):
            await budget.take("critical")
        self.assertEqual(budget.snapshot()["refused_60s"], 1)
        budget._refusals = [time.monotonic() - 61]
        self.assertEqual(budget.snapshot()["refused_60s"], 0)

    @expects_logs()
    def test_a_venue_block_sets_cooling_until(self) -> None:
        before = int(time.time() * 1000)
        budget.note_blocked()
        until = budget.snapshot()["cooling_until"]
        self.assertGreater(until, before)
        self.assertLess(until, before + 70_000)
        budget._cool_until = time.monotonic() - 1
        self.assertEqual(budget.snapshot()["cooling_until"], 0)

    async def test_the_publisher_sends_nothing_when_nothing_changed(self) -> None:
        from mayedge.lighter.budget import publish_changes

        sent: list[dict[str, object]] = []
        ticks = 0

        async def sleep(_seconds: float) -> None:
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                self.assertTrue(budget.try_acquire(tx=True))
            if ticks > 3:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await publish_changes(sent.append, sleep=sleep)
        self.assertEqual([row["tx"] for row in sent], [0, 1])


class NonceAndOrderTests(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        budget.reset()

    @expects_logs()
    async def test_invalid_nonce_retries_once(self) -> None:
        svc = OrderService()
        calls = 0

        async def send():
            nonlocal calls
            calls += 1
            if calls == 1:
                return None, SimpleNamespace(code=21104, message="invalid nonce"), None
            return None, SimpleNamespace(code=200, tx_hash="0xok"), None

        _tx, resp, err = await svc._retry_nonce(send)
        self.assertEqual(calls, 2)
        self.assertEqual(resp.tx_hash, "0xok")
        self.assertIsNone(err)

    async def test_update_leverage_reads_the_send_response(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.update_leverage = AsyncMock(
            return_value=("tx", SimpleNamespace(code=200, tx_hash="0xlev"), None)
        )
        meta = MarketMeta(1, "ETH", 2, 4, 0.001, 10.0)
        lev = meta.allowed_leverages[0]
        with patch.object(svc, "_market_meta", return_value=meta):
            out = await svc.update_leverage(1, lev)
        self.assertEqual(out["tx_hash"], "0xlev")
        self.assertEqual(out["leverage"], lev)

    async def test_update_leverage_rejects_a_non_200(self) -> None:
        svc = OrderService()
        svc._signer = MagicMock()
        svc._signer.update_leverage = AsyncMock(
            return_value=("tx", SimpleNamespace(code=400, message="no", tx_hash="0xno"), None)
        )
        meta = MarketMeta(1, "ETH", 2, 4, 0.001, 10.0)
        with (
            patch.object(svc, "_market_meta", return_value=meta),
            self.assertRaises(ValueError),
        ):
            await svc.update_leverage(1, meta.allowed_leverages[0])

    def test_order_error_codes_are_readable(self) -> None:
        svc = OrderService()
        meta = MarketMeta(1, "ETH", 2, 4, 0.001, 10.0)
        cases = {
            "21711": "5 minutes",
            "21719": "Pending order cap",
            "21720": "Pending order cap",
            "21728": "Duplicate client order id",
        }
        for code, snippet in cases.items():
            with self.assertRaises(ValueError) as ctx:
                svc._raise_order_err(f"code={code}", meta)
            self.assertIn(snippet, str(ctx.exception))

    def test_native_twap_schema_rejects_under_five_minutes(self) -> None:
        with self.assertRaises(ValidationError):
            TwapOrderRequest(market_index=1, side="buy", size="1", duration_seconds=299)
        ok = TwapOrderRequest(market_index=1, side="buy", size="1", duration_seconds=300)
        self.assertEqual(ok.duration_seconds, 300)

    def test_market_price_uses_stats_when_the_book_is_unsynced(self) -> None:
        svc = OrderService()
        meta = MarketMeta(
            1,
            "ETH",
            2,
            4,
            0.001,
            10.0,
            last_trade_price=100.0,
            best_bid_price=180.0,
            best_ask_price=200.0,
        )
        with patch("mayedge.lighter.orders.gateway.best_bid_ask", return_value=(None, None)):
            buy = svc._market_worst_price(meta, is_ask=False, slippage=0)
            sell = svc._market_worst_price(meta, is_ask=True, slippage=0)
        self.assertEqual(buy, 20000)
        self.assertEqual(sell, 18000)


class AlgoBudgetTests(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        budget.reset()

    def test_local_refusal_holds_the_clip(self) -> None:
        job = ChaseIcebergRunner.__new__(ChaseIcebergRunner)
        held: list[str] = []
        job._hold_clip = lambda reason: held.append(reason)  # type: ignore[method-assign]
        self.assertTrue(job._handle_tx_err(BudgetRefused(429, "full")))
        self.assertEqual(held, ["budget"])

    async def test_order_not_found_does_not_replace_immediately(self) -> None:
        job = ChaseIcebergRunner.__new__(ChaseIcebergRunner)
        job._state = SimpleNamespace(market_index=1)  # type: ignore[assignment]
        placed: list[object] = []
        resolved: list[object] = []

        async def place(quote: object) -> None:
            placed.append(quote)

        async def resolve(clip: object, now: int) -> None:
            resolved.append(clip)

        job._place_working = place  # type: ignore[method-assign]
        job._resolve_vanished_clip = resolve  # type: ignore[method-assign]
        job._modify_index = lambda _clip: 9  # type: ignore[method-assign]
        job._market_view = lambda: None  # type: ignore[method-assign]

        async def modify_order(**_kwargs: object) -> None:
            raise ValueError("order not found")

        job._exec = lambda: SimpleNamespace(modify_order=modify_order)  # type: ignore[method-assign]
        clip = SimpleNamespace(remaining=Decimal("1"))
        quote = SimpleNamespace(qty=Decimal("1"), price=Decimal("100"))
        await job._modify_working(clip, quote)
        self.assertEqual(resolved, [clip])
        self.assertEqual(placed, [])

    async def test_ladder_syncs_every_live_rung(self) -> None:
        runner = LadderRunner.__new__(LadderRunner)
        clips = ["older", "newest"]
        runner._state = SimpleNamespace(  # type: ignore[assignment]
            ledger=SimpleNamespace(live_clips=lambda: list(clips))
        )
        seen: list[str] = []

        async def sync(clip: str) -> None:
            seen.append(clip)

        runner._sync_clip = sync  # type: ignore[method-assign]
        runner._drain_trades = lambda: None  # type: ignore[method-assign]
        runner._reconcile_master = lambda: None  # type: ignore[method-assign]
        await runner._sync_fills()
        self.assertEqual(seen, ["older", "newest"])


class ToneWsTests(IsolatedAsyncioTestCase):
    @expects_logs()
    async def test_error_frame_is_not_applied_as_a_book(self) -> None:
        gw = LighterGateway.__new__(LighterGateway)
        gw._books = OrderBookFeed(lambda _msg: None)
        gw._books.set_current_market(120)
        await handle_ws_message(
            gw,
            {
                "error": {"code": 30003, "message": "Already Subscribed"},
                "type": "subscribed/order_book",
                "channel": "order_book:120",
                "order_book": {
                    "bids": [{"price": "1", "size": "1"}],
                    "asks": [{"price": "2", "size": "1"}],
                },
            },
        )
        self.assertFalse(gw._books.has_book(120))

    async def test_pacer_spaces_the_second_send(self) -> None:
        pacer = SendPacer(per_min=150)
        await pacer.wait()
        started = time.monotonic()
        await pacer.wait()
        self.assertGreaterEqual(time.monotonic() - started, 0.3)

    def test_tone_channels_cover_every_perp_timeframe(self) -> None:
        from mayedge.tone_alerts import ToneBook

        gw = LighterGateway.__new__(LighterGateway)
        gw._markets = {
            1: MarketMeta(1, "ETH", 2, 4, 0.001, 10.0),
            2: MarketMeta(2, "BTC", 1, 5, 0.001, 10.0),
        }
        gw._tone_book = ToneBook(timeframes=("30m", "4h"))
        self.assertEqual(
            gw.tone_channels(),
            [
                "candle/1/1m",
                "candle/1/30m",
                "candle/1/4h",
                "candle/2/1m",
                "candle/2/30m",
                "candle/2/4h",
            ],
        )


class KillHeadroomTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        budget.reset()

    def tearDown(self) -> None:
        budget.reset()

    def test_algos_leave_transactions_for_a_manual_order(self) -> None:
        sent = 0
        while budget.try_acquire(lane="algo", tx=True):
            sent += 1
        self.assertEqual(sent, TX_CEILING["algo"])
        self.assertLess(sent, TX_CAP)
        self.assertTrue(budget.try_acquire(lane="critical", tx=True))

    def test_kill_is_sent_through_a_full_window(self) -> None:
        while budget.try_acquire(lane="critical", tx=True):
            pass
        self.assertFalse(budget.try_acquire(lane="critical", tx=True))
        self.assertTrue(budget.try_acquire(lane=KILL_LANE, tx=True))

    @expects_logs()
    def test_kill_is_sent_through_the_venue_cooldown(self) -> None:
        budget.note_blocked()
        self.assertFalse(budget.try_acquire(lane="critical", tx=True))
        self.assertTrue(budget.try_acquire(lane=KILL_LANE, tx=True))

    async def test_run_kill_sends_in_the_kill_lane(self) -> None:
        from mayedge.api import app as api_app
        from mayedge.kill import KillResult
        from mayedge.lighter.budget import _lane

        seen: list[str] = []

        async def fake_kill(**_kwargs):
            seen.append(_lane.get())
            return KillResult(status="killed", cancel_ok=True, cancel_error=None, flatten=[])

        with patch.object(api_app, "kill", fake_kill):
            await api_app.run_kill(flatten=False)
        self.assertEqual(seen, [KILL_LANE])
        self.assertEqual(_lane.get(), "critical")
