"""ChaseIcebergRunner + ChaseBook integration tests (fake clock / venue)."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from decimal import Decimal
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from mayedge.algos.chase import (
    ChaseIcebergRunner,
    ChaseStatus,
)
from mayedge.algos.chase.config import (
    CHASE_COI_BASE,
    CHASE_COI_END,
    MIN_REQUOTE_MS,
    MISSING_FILL_GRACE_MS,
    RATE_LIMIT_COOLDOWN_MS,
    STALE_ACK_MS,
)
from mayedge.config import settings

# Allow `from chase_harness import ...` when discover runs from backend/
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from chase_harness import (  # noqa: E402
    BootedJob,
    FakeClock,
    FakeGateway,
    FakeOrderService,
    boot_job,
    buy_params,
    isolated_db,
    make_test_book,
    patch_chase,
    trade_print,
)

D = Decimal


class IsolatedChaseTestCase(IsolatedAsyncioTestCase):
    """Runner tests must not upsert into ./data/mayedge.db."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._db = isolated_db()
        cls._db.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._db.__exit__(None, None, None)


class ChaseRunnerPlaceTests(IsolatedChaseTestCase):
    async def test_fresh_evaluate_rests_clip(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(boot.orders.creates[0]["price"], "99.96")
        self.assertEqual(boot.orders.creates[0]["size"], "1")
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertEqual(live.price, D("99.96"))
        self.assertEqual(live.qty, D("1"))
        self.assertEqual(boot.job.state.remaining, D("10"))
        self.assertEqual(boot.job.state.quote_action, "rest")

    async def test_trading_disabled_errors(self) -> None:
        boot = boot_job()
        boot.orders.enabled = False
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
        self.assertEqual(boot.job.state.error, "Trading not configured")
        self.assertEqual(boot.orders.creates, [])

    async def test_no_market_pauses(self) -> None:
        boot = boot_job()
        boot.gateway.hide_market()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.quote_action, "pause")
        self.assertEqual(boot.job.state.reason, "no_market")
        self.assertEqual(boot.orders.creates, [])

    async def test_pause_cancels_working_without_invent_fill(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            live = boot.job.state.ledger.working()
            assert live is not None
            self.assertTrue(live.seen_on_book)
            boot.gateway.set_book("89.00", "89.50")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.quote_action, "pause")
        self.assertEqual(boot.job.state.reason, "below_floor")
        self.assertEqual(len(boot.orders.cancels), 1)
        self.assertIsNone(boot.job.state.ledger.working())
        clip = boot.job.state.ledger.find_clip(client_order_index=coi)
        assert clip is not None
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(clip.filled, D("0"))
        self.assertEqual(boot.job.state.filled, D("0"))

    async def test_remaining_zero_finishes_done(self) -> None:
        boot = boot_job(params=buy_params(qty=D("1"), display_qty=D("1")))
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            oid = boot.orders.creates[0]["order_index"]
            boot.job._pending_trades.append(
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=1,
                    bid_client_id=coi,
                    bid_id=oid,
                )
            )
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.status, ChaseStatus.DONE)
        self.assertNotIn(boot.algo_id, boot.book._jobs)
        self.assertEqual(boot.book._archive[0]["status"], "done")


class ChaseRunnerRequoteTests(IsolatedChaseTestCase):
    async def test_partial_same_price_does_not_replace(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.set_remaining(coi, "0.4", filled="0.6")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(boot.orders.cancels, [])
        self.assertEqual(boot.orders.modifies, [])
        self.assertEqual(boot.job.state.filled, D("0.6"))
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertEqual(live.remaining, D("0.4"))

    async def test_partial_price_move_requotes(self) -> None:
        """A partial still chases — amend price when the passive price moves."""
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.set_remaining(coi, "0.4", filled="0.6")
            await boot.job._evaluate()
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(len(boot.orders.modifies), 1)
        self.assertEqual(boot.orders.modifies[0]["price"], "99.95")
        self.assertEqual(boot.orders.modifies[0]["size"], "0.4")
        self.assertEqual(boot.orders.cancels, [])
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertEqual(live.client_order_index, coi)
        self.assertEqual(live.price, D("99.95"))
        self.assertEqual(live.remaining, D("0.4"))
        self.assertEqual(live.status, "live")

    async def test_partial_below_min_qty_replaces_with_new_clip(self) -> None:
        """Sub-min leftover cannot amend — cancel it and rest a full display clip."""
        gateway = FakeGateway()
        assert gateway.market is not None
        gateway.market.min_base_amount = 0.5
        boot = boot_job(gateway=gateway)
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            first_coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.set_remaining(first_coi, "0.4", filled="0.6")
            await boot.job._evaluate()
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 2)
        self.assertEqual(len(boot.orders.cancels), 1)
        self.assertEqual(boot.orders.modifies, [])
        self.assertEqual(boot.job.state.filled, D("0.6"))
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertNotEqual(live.client_order_index, first_coi)
        self.assertEqual(live.qty, D("1"))
        self.assertEqual(live.price, D("99.95"))
        self.assertEqual(live.status, "live")

    async def test_partial_that_would_cross_is_pulled(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.set_remaining(coi, "0.4", filled="0.6")
            await boot.job._evaluate()
            boot.gateway.set_book("99.80", "99.90")
            boot.clock.advance(100)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.cancels), 1)
        live = boot.job.state.ledger.working()
        self.assertIsNone(live)

    async def test_price_move_after_cooldown_requotes(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            first_coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(len(boot.orders.modifies), 1)
        self.assertEqual(boot.orders.modifies[0]["price"], "99.95")
        self.assertEqual(boot.orders.modifies[0]["size"], "1")
        self.assertEqual(boot.orders.cancels, [])
        self.assertEqual(boot.job.state.rest_price, D("99.95"))
        old = boot.job.state.ledger.find_clip(client_order_index=first_coi)
        assert old is not None
        self.assertEqual(old.status, "live")
        self.assertEqual(old.price, D("99.95"))

    async def test_price_move_inside_cooldown_no_replace(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._evaluate()
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(100)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(boot.orders.cancels, [])
        self.assertEqual(boot.orders.modifies, [])
        self.assertEqual(boot.job.state.rest_price, D("99.96"))
        self.assertEqual(boot.job.state.reason, "requote_wait")

    async def test_unacked_within_ack_wait_no_replace(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            live = boot.job.state.ledger.working()
            assert live is not None
            live.seen_on_book = False
            live.order_index = None
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(500)
            n_creates = len(boot.orders.creates)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), n_creates)
        self.assertEqual(boot.orders.cancels, [])
        self.assertEqual(boot.orders.modifies, [])

    async def test_unacked_past_stale_ack_rest_gone_errors_no_replace(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.remove_by_coi(coi)
            boot.orders.cached_orders_override = []
            live = boot.job.state.ledger.working()
            assert live is not None
            live.seen_on_book = False
            live.order_index = None
            boot.clock.advance(STALE_ACK_MS + 1)
            await boot.job._evaluate()
        clip = boot.job.state.ledger.find_clip(client_order_index=coi)
        assert clip is not None
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
        self.assertEqual(boot.job.state.error, "unproven_missing_clip")
        self.assertEqual(len(boot.orders.creates), 1)

    async def test_unacked_past_stale_ack_rest_still_open_acks(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            boot.orders.cached_orders_override = []
            live = boot.job.state.ledger.working()
            assert live is not None
            live.seen_on_book = False
            live.order_index = None
            boot.clock.advance(STALE_ACK_MS + 1)
            await boot.job._evaluate()
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertTrue(live.seen_on_book)
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)

    async def test_unacked_past_stale_ack_rest_gone_trades_then_replace(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.remove_by_coi(coi)
            boot.orders.cached_orders_override = []
            live = boot.job.state.ledger.working()
            assert live is not None
            live.seen_on_book = False
            live.order_index = None
            boot.orders.trades_response = [
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=7,
                    bid_client_id=coi,
                )
            ]
            boot.clock.advance(STALE_ACK_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)
        self.assertEqual(boot.job.state.filled, D("1"))
        self.assertEqual(boot.job.state.remaining, D("9"))
        self.assertEqual(len(boot.orders.creates), 2)


class ChaseRunnerCrossAndErrorsTests(IsolatedChaseTestCase):
    async def test_must_pull_during_cooldown_cancels_only(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._evaluate()
            boot.gateway.set_book("99.80", "99.90")
            boot.clock.advance(100)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.cancels), 1)
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertIsNone(boot.job.state.ledger.working())

    async def test_empty_book_re_rests_inside_requote_window(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._evaluate()
            boot.gateway.set_book("99.80", "99.90")
            boot.clock.advance(100)
            await boot.job._evaluate()
            self.assertIsNone(boot.job.state.ledger.working())
            await boot.job._evaluate()
        self.assertGreaterEqual(len(boot.orders.creates), 2)

    async def test_modify_would_cross_keeps_resting_clip(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._evaluate()
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            boot.orders.modify_error = ValueError("post only order would cross (code 2170)")
            await boot.job._evaluate()
        self.assertEqual(boot.orders.cancels, [])
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertEqual(live.price, D("99.96"))

    async def test_modify_min_size_replaces_with_new_clip(self) -> None:
        """Venue min-size on amend abandons leftover and rests a new display clip."""
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            first_coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.set_remaining(first_coi, "0.4", filled="0.6")
            await boot.job._evaluate()
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            boot.orders.modify_error = ValueError("Min 3.5 LIT (or $10)")
            await boot.job._evaluate()
            n = len(boot.orders.modify_attempts)
            boot.clock.advance(100)
            await boot.job._evaluate()
        self.assertEqual(n, 1)
        self.assertEqual(len(boot.orders.modify_attempts), 1)
        self.assertEqual(len(boot.orders.creates), 2)
        self.assertEqual(len(boot.orders.cancels), 1)
        self.assertEqual(boot.job.state.filled, D("0.6"))
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertNotEqual(live.client_order_index, first_coi)
        self.assertEqual(live.qty, D("1"))
        self.assertEqual(live.price, D("99.95"))

    async def test_post_only_reject_pauses_would_cross(self) -> None:
        boot = boot_job()
        boot.orders.create_error = ValueError("post only order would cross (code 2170)")
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.quote_action, "pause")
        self.assertEqual(boot.job.state.reason, "would_cross")
        self.assertIsNone(boot.job.state.ledger.working())

    async def test_create_rate_limit_sets_backoff(self) -> None:
        boot = boot_job()
        boot.orders.create_error = RuntimeError("429 too many requests")
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(boot.job.state.reason, "rate_limited")
            self.assertEqual(boot.job._backoff_until, boot.clock.now_ms + RATE_LIMIT_COOLDOWN_MS)
            boot.orders.create_error = None
            await boot.job._evaluate()
            self.assertEqual(boot.orders.creates, [])
            self.assertIn(boot.job.state.reason, ("rate_limited", "requote_wait"))

    async def test_create_invalid_nonce_keeps_job_running(self) -> None:
        boot = boot_job()
        boot.orders.create_error = ValueError(
            "HTTP response body: code=21104 message='invalid nonce'"
        )
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)
            self.assertEqual(boot.job.state.reason, "invalid_nonce")
            self.assertEqual(boot.orders.creates, [])
            self.assertGreater(boot.job._backoff_until, boot.clock.now_ms)
            boot.orders.create_error = None
            await boot.job._evaluate()
            self.assertEqual(boot.orders.creates, [])
            self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)
            self.assertEqual(boot.job.state.reason, "invalid_nonce")
            boot.clock.advance(RATE_LIMIT_COOLDOWN_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)


class ChaseRunnerFillSyncTests(IsolatedChaseTestCase):
    async def test_trade_print_credits_fill(self) -> None:
        boot = boot_job(params=buy_params(qty=D("2"), display_qty=D("1")))
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            oid = boot.orders.creates[0]["order_index"]
            boot.job._pending_trades.append(
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=11,
                    bid_client_id=coi,
                    bid_id=oid,
                )
            )
            boot.orders.remove_by_coi(coi)
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.filled, D("1"))
        self.assertEqual(boot.job.state.remaining, D("1"))
        self.assertEqual(len(boot.orders.creates), 2)

    async def test_trade_dedupe_by_trade_id(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            oid = boot.orders.creates[0]["order_index"]
            t = trade_print(
                market_index=1,
                size="0.4",
                price="99.96",
                trade_id=42,
                bid_client_id=coi,
                bid_id=oid,
            )
            boot.job._pending_trades.extend([t, dict(t)])
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.filled, D("0.4"))
        self.assertEqual(len(boot.job.state.ledger.fills), 1)

    async def test_open_order_remaining_drop_partial(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            boot.orders.set_remaining(coi, "0.3", filled="0.7")
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.filled, D("0.7"))
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertEqual(live.remaining, D("0.3"))

    async def test_vanish_before_grace_sets_missing_since(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
            live = boot.job.state.ledger.working()
            assert live is not None
            self.assertIsNotNone(live.missing_since)
            self.assertEqual(live.status, "live")
            self.assertEqual(boot.job.state.filled, D("0"))

    async def test_vanish_after_grace_errors_without_evidence(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
            boot.clock.advance(MISSING_FILL_GRACE_MS + 1)
            await boot.job._evaluate()
        clip = boot.job.state.ledger.find_clip(client_order_index=coi)
        assert clip is not None
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(clip.filled, D("0"))
        self.assertEqual(boot.job.state.filled, D("0"))
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
        self.assertEqual(boot.job.state.error, "unproven_missing_clip")

    async def test_vanish_ws_lag_rest_still_open_does_not_error(self) -> None:
        """WS cache drop is not a fill when REST still lists the child."""
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            still = dict(boot.orders.find_by_coi(coi) or {})
            boot.orders.remove_by_coi(coi)
            boot.orders.summary_orders_override = [still]
            await boot.job._evaluate()
            boot.clock.advance(MISSING_FILL_GRACE_MS + 1)
            await boot.job._evaluate()
        clip = boot.job.state.ledger.find_clip(client_order_index=coi)
        assert clip is not None
        self.assertEqual(clip.status, "live")
        self.assertEqual(boot.job.state.filled, D("0"))
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)
        self.assertNotEqual(boot.job.state.error, "unproven_missing_clip")

    async def test_vanish_with_full_trade_coverage_fills_once(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            oid = boot.orders.creates[0]["order_index"]
            await boot.job._evaluate()
            boot.job._pending_trades.append(
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=9,
                    bid_client_id=coi,
                    bid_id=oid,
                )
            )
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.filled, D("1"))
        self.assertEqual(len(boot.job.state.ledger.fills), 1)

    async def test_requote_modifies_even_when_open_cache_empty(self) -> None:
        """A wiped open-order cache still amends by client_order_index."""
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            first = boot.orders.creates[0]
            await boot.job._evaluate()
            live = boot.job.state.ledger.working()
            assert live is not None
            self.assertTrue(live.seen_on_book)
            boot.orders.open_orders = []
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.modify_attempts), 1)
        self.assertEqual(
            boot.orders.modify_attempts[0]["order_index"], first["client_order_index"]
        )
        self.assertEqual(len(boot.orders.modifies), 0)
        self.assertEqual(len(boot.orders.creates), 2)
        self.assertEqual(boot.orders.cancels, [])
        old = boot.job.state.ledger.find_clip(client_order_index=first["client_order_index"])
        assert old is not None
        self.assertEqual(old.status, "cancelled")
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertNotEqual(live.client_order_index, first["client_order_index"])

    async def test_requote_cancel_path_does_not_invent_fill(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            first_coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.remove_by_coi(first_coi)
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        old = boot.job.state.ledger.find_clip(client_order_index=first_coi)
        assert old is not None
        self.assertEqual(old.status, "cancelled")
        self.assertEqual(old.filled, D("0"))
        self.assertEqual(len(boot.orders.creates), 2)
        self.assertEqual(boot.orders.cancels, [])

    async def test_other_market_trade_ignored(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            oid = boot.orders.creates[0]["order_index"]
            boot.job._pending_trades.append(
                trade_print(
                    market_index=99,
                    size="1",
                    price="99.96",
                    trade_id=1,
                    bid_client_id=coi,
                    bid_id=oid,
                )
            )
            await boot.job._evaluate()
        self.assertEqual(boot.job.state.filled, D("0"))


class ChaseBookStopTests(IsolatedChaseTestCase):
    async def test_stop_cancels_children_and_archives(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(len(boot.orders.open_orders), 1)
            await boot.book.stop(boot.algo_id)
        self.assertEqual(boot.job.state.status, ChaseStatus.STOPPED)
        self.assertEqual(boot.orders.open_orders, [])
        self.assertEqual(len(boot.orders.cancels), 1)
        self.assertNotIn(boot.algo_id, boot.book._jobs)
        self.assertEqual(boot.book._archive[0]["algo_id"], boot.algo_id)

    async def test_stop_refresh_when_cache_miss(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._evaluate()
            row = dict(boot.orders.open_orders[0])
            # Force stop to discover the child via summary refresh, not ledger/cache.
            live = boot.job.state.ledger.working()
            assert live is not None
            live.order_index = None
            boot.orders.open_orders = []
            boot.orders.set_summary_sequence([], [row])

            async def _nosleep(_: float) -> None:
                await asyncio.sleep(0)

            with patch("mayedge.algos.chase.job.asyncio.sleep", _nosleep):
                await boot.book.stop(boot.algo_id)
        self.assertGreaterEqual(boot.orders.summary_calls, 2)
        self.assertEqual(boot.job.state.status, ChaseStatus.STOPPED)
        self.assertIn((int(row["market_index"]), int(row["order_index"])), boot.orders.cancels)

    async def test_two_jobs_stop_one_leaves_other(self) -> None:
        clock = FakeClock()
        gateway = FakeGateway()
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        a = boot_job(algo_id="CH-0001", clock=clock, gateway=gateway, orders=orders)
        a.job._book = book
        book._jobs["CH-0001"] = a.job
        b = boot_job(algo_id="CH-0002", clock=clock, gateway=gateway, orders=orders)
        b.job._book = book
        book._jobs["CH-0002"] = b.job
        with patch_chase(clock, gateway, orders):
            await a.job._evaluate()
            await b.job._evaluate()
            self.assertEqual(len(orders.creates), 2)
            await book.stop("CH-0001")
            self.assertEqual(a.job.state.status, ChaseStatus.STOPPED)
            self.assertEqual(b.job.state.status, ChaseStatus.RUNNING)
            self.assertIn("CH-0002", book._jobs)
            self.assertNotIn("CH-0001", book._jobs)

    async def test_coi_exhaustion(self) -> None:
        gateway = FakeGateway()
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        # Next alloc yields CHASE_COI_END - 1; the one after that exhausts.
        book._coi_seq = CHASE_COI_END - CHASE_COI_BASE - 2
        last = book.alloc_coi()
        self.assertEqual(last, CHASE_COI_END - 1)
        with self.assertRaises(RuntimeError):
            book.alloc_coi()

    async def test_start_validation_and_place(self) -> None:
        clock = FakeClock()
        gateway = FakeGateway()
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        with patch_chase(clock, gateway, orders):
            await book.start(market_index=1, params=buy_params())
            self.assertEqual(len(book._jobs), 1)
            job = next(iter(book._jobs.values()))
            self.assertEqual(job.state.status, ChaseStatus.RUNNING)
            self.assertEqual(len(orders.creates), 1)
            if job._task:
                job._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await job._task
                job._task = None
            await book.stop()


class ChaseCancelSafetyTests(IsolatedChaseTestCase):
    async def test_cancel_fail_keeps_clip_and_no_second_place(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._evaluate()
            boot.orders.cancel_error = RuntimeError("venue down")
            boot.gateway.set_book("99.99", "100.10")
            boot.clock.advance(MIN_REQUOTE_MS + 1)
            await boot.job._evaluate()
        self.assertEqual(len(boot.orders.creates), 1)
        live = boot.job.state.ledger.working()
        assert live is not None
        self.assertEqual(live.status, "live")

    async def test_stop_with_cancel_fail_stays_error(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            boot.orders.cancel_error = RuntimeError("cancel failed")
            await boot.book.stop(boot.algo_id)
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
        self.assertIn(boot.algo_id, boot.book._jobs)
        self.assertGreater(len(boot.orders.open_orders), 0)

    async def test_stop_succeeds_when_ws_cache_lags(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            stale = {"open_orders": list(boot.orders.open_orders), "type": "account"}
            boot.orders.cached_account_payload = lambda: stale  # type: ignore[method-assign]
            await boot.book.stop(boot.algo_id)
        self.assertEqual(boot.job.state.status, ChaseStatus.STOPPED)
        self.assertNotIn(boot.algo_id, boot.book._jobs)
        self.assertEqual(boot.orders.open_orders, [])

    async def test_stop_retries_invalid_nonce_then_succeeds(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            boot.orders.cancel_error_once = ValueError(
                "HTTP response body: code=21104 message='invalid nonce'"
            )
            await boot.book.stop(boot.algo_id)
        self.assertEqual(boot.job.state.status, ChaseStatus.STOPPED)
        self.assertNotIn(boot.algo_id, boot.book._jobs)
        self.assertEqual(boot.orders.open_orders, [])

    async def test_stop_order_not_found_still_stops(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            boot.orders.cancel_error = ValueError("order not found (21701)")
            boot.orders.open_orders = []
            await boot.book.stop(boot.algo_id)
        self.assertEqual(boot.job.state.status, ChaseStatus.STOPPED)
        self.assertNotIn(boot.algo_id, boot.book._jobs)

    async def test_restore_error_does_not_quote(self) -> None:
        boot = boot_job()
        row = {
            "algo_id": boot.algo_id,
            "status": "error",
            "market_index": 1,
            "symbol": "ETH",
            "side": "buy",
            "qty": "10",
            "display_qty": "1",
            "offset_bps": "4",
            "price_floor": "90",
            "price_ceiling": "100",
            "remaining": "10",
            "filled": "0",
            "error": "resume evaluate failed",
            "clips": [],
            "fills": [],
            "trade_ids": set(),
            "trade_qty_by_clip": {},
            "next_clip": 1,
            "next_fill": 1,
        }
        boot.job.hydrate_from_row(row)
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job.resume()
        self.assertEqual(len(boot.orders.creates), 0)
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)

    async def test_vanish_unhydrated_does_not_invent_fill(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.orders_hydrated = False
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
            boot.clock.advance(MISSING_FILL_GRACE_MS + 1)
            await boot.job._evaluate()
        clip = boot.job.state.ledger.find_clip(client_order_index=coi)
        assert clip is not None
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(clip.filled, D("0"))
        self.assertEqual(boot.job.state.filled, D("0"))
        self.assertNotEqual(boot.job.state.status, ChaseStatus.DONE)


class ChaseStartNotionalTests(IsolatedChaseTestCase):
    async def test_parent_over_cap_rejects(self) -> None:
        clock = FakeClock()
        gateway = FakeGateway()
        gateway.set_book("100", "100.10")
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        job = ChaseIcebergRunner(book)
        with (
            patch_chase(clock, gateway, orders),
            patch.object(settings, "max_order_notional", 50_000.0),
            self.assertRaisesRegex(ValueError, "exceeds limit"),
        ):
            await job.start(
                algo_id="CH-cap",
                market_index=1,
                params=buy_params(qty=D("1000"), display_qty=D("1")),
            )

    async def test_parent_under_cap_starts(self) -> None:
        clock = FakeClock()
        gateway = FakeGateway()
        gateway.set_book("100", "100.10")
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        job = ChaseIcebergRunner(book)
        with (
            patch_chase(clock, gateway, orders),
            patch.object(settings, "max_order_notional", 50_000.0),
        ):
            await job.start(
                algo_id="CH-ok",
                market_index=1,
                params=buy_params(qty=D("10"), display_qty=D("1")),
            )
        self.assertEqual(job.state.status, ChaseStatus.RUNNING)
        self.assertEqual(len(orders.creates), 1)


class ChaseAccumulateSafetyTests(IsolatedChaseTestCase):
    async def test_book_unsynced_pulls_clip(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(len(boot.orders.creates), 1)
            boot.gateway.set_book(None, None)
            await boot.job._evaluate()
        self.assertIsNone(boot.job.state.ledger.working())
        self.assertEqual(boot.job.state.reason, "book_unsynced")
        self.assertEqual(len(boot.orders.cancels), 1)

    async def test_account_unsynced_pulls_clip(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(len(boot.orders.creates), 1)
            boot.orders.account_ws_live_flag = False
            await boot.job._evaluate()
        self.assertIsNone(boot.job.state.ledger.working())
        self.assertEqual(boot.job.state.reason, "account_unsynced")

    async def test_duplicate_market_side_rejected(self) -> None:
        clock = FakeClock()
        gateway = FakeGateway()
        gateway.set_book("100", "100.10")
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        with patch_chase(clock, gateway, orders):
            await book.start(
                market_index=1,
                params=buy_params(),
                reduce_only=False,
            )
            with self.assertRaisesRegex(ValueError, "already running"):
                await book.start(
                    market_index=1,
                    params=buy_params(),
                    reduce_only=False,
                )

    async def test_drain_for_shutdown_pulls_clip(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(len(boot.orders.creates), 1)
            await boot.job.drain_for_shutdown()
        self.assertIsNone(boot.job.state.ledger.working())
        self.assertEqual(boot.job.state.reason, "shutdown")
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)

    async def test_pause_for_market_before_cancel_all(self) -> None:
        clock = FakeClock()
        gateway = FakeGateway()
        gateway.set_book("100", "100.10")
        orders = FakeOrderService()
        book = make_test_book(gateway, orders)
        with patch_chase(clock, gateway, orders):
            await book.start(market_index=1, params=buy_params(), reduce_only=False)
            algo_id = next(iter(book._jobs.keys()))
            await book.pause_for_market(1)
        job = book._jobs[algo_id]
        self.assertEqual(job.state.status, ChaseStatus.PAUSED)
        self.assertIsNone(job.state.ledger.working())

    async def test_resume_account_down_does_not_place(self) -> None:
        boot = boot_job()
        boot.orders.account_ws_live_flag = False
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job.resume()
        self.assertEqual(len(boot.orders.creates), 0)
        self.assertEqual(boot.job.state.reason, "account_unsynced")
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)


class ChaseOvernightTrustTests(IsolatedChaseTestCase):
    def _persist_row(self, boot: BootedJob, *, status: str = "running") -> dict:
        job = boot.job
        p = job.state.params
        assert p is not None
        ledger = job.state.ledger
        return {
            "algo_id": boot.algo_id,
            "status": status,
            "market_index": job.state.market_index,
            "symbol": job.state.symbol,
            "side": p.side,
            "qty": str(p.qty),
            "display_qty": str(p.display_qty),
            "offset_bps": str(p.offset_bps),
            "price_floor": str(p.price_floor),
            "price_ceiling": str(p.price_ceiling),
            "remaining": str(job.state.remaining),
            "filled": str(job.state.filled),
            "error": job.state.error,
            "clips": [c.to_persist() for c in ledger.clips],
            "fills": [f.to_persist() for f in ledger.fills],
            "trade_ids": set(ledger.trade_ids),
            "trade_qty_by_clip": {k: str(v) for k, v in ledger.trade_qty_by_clip.items()},
            "next_clip": ledger.next_clip,
            "next_fill": ledger.next_fill,
        }

    async def test_resume_pulls_crash_leftover_then_new_clip(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            self.assertEqual(len(boot.orders.creates), 1)
            old_coi = boot.orders.creates[0]["client_order_index"]
            row = self._persist_row(boot)
            boot.job.hydrate_from_row(row)
            await boot.job.resume()
        self.assertEqual(len(boot.orders.creates), 2)
        self.assertNotEqual(boot.orders.creates[1]["client_order_index"], old_coi)
        self.assertIsNone(boot.orders.find_by_coi(old_coi))
        self.assertEqual(boot.job.state.remaining, D("10"))
        self.assertEqual(boot.job.state.filled, D("0"))

    async def test_unpause_credits_missed_fill_before_quote(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
            boot.clock.advance(MISSING_FILL_GRACE_MS + 1)
            await boot.job._evaluate()
            self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
            self.assertEqual(boot.job.state.error, "unproven_missing_clip")
            self.assertEqual(boot.job.state.remaining, D("10"))
            boot.orders.trades_response = [
                trade_print(
                    market_index=1,
                    size="1",
                    price="99.96",
                    trade_id=42,
                    bid_client_id=coi,
                )
            ]
            await boot.job.unpause()
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)
        self.assertEqual(boot.job.state.remaining, D("9"))
        self.assertEqual(boot.job.state.filled, D("1"))
        self.assertEqual(len(boot.orders.creates), 2)
        self.assertEqual(boot.orders.creates[1]["size"], "1")

    async def test_error_restore_pulls_leftover_no_quote(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            row = self._persist_row(boot, status="error")
            row["error"] = "unproven_missing_clip"
            boot.job.hydrate_from_row(row)
            await boot.job.resume()
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertIsNone(boot.orders.find_by_coi(coi))

    async def test_unpause_trades_fail_stays_error(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
            boot.clock.advance(MISSING_FILL_GRACE_MS + 1)
            await boot.job._evaluate()
            self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
            boot.orders.trades_error = ValueError("trades down")
            await boot.job.unpause()
        self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
        self.assertEqual(boot.job.state.error, "trades_reconcile_failed")
        self.assertEqual(len(boot.orders.creates), 1)


class ChaseOvershootSafetyTests(IsolatedChaseTestCase):
    async def test_place_blocked_when_rest_shows_child(self) -> None:
        from mayedge.algos.chase.iceberg import decide

        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            live = boot.job.state.ledger.working()
            assert live is not None
            view = boot.job._market_view()
            assert view is not None
            params = boot.job.state.params
            assert params is not None
            q = decide(params, view, boot.job.state.remaining)
            boot.job.state.ledger.close_missing(live, canceling=True, now=boot.clock())
            await boot.job._place_working(q)
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertEqual(boot.job.state.reason, "child_still_open")

    async def test_cancel_lag_keeps_ledger_live(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            boot.orders.cancel_keeps_open = True
            await boot.job._cancel_working()
        self.assertIsNotNone(boot.job.state.ledger.working())
        self.assertEqual(len(boot.orders.creates), 1)
        self.assertGreaterEqual(len(boot.orders.cancels), 1)

    async def test_cancel_verified_gone_allows_replace(self) -> None:
        from mayedge.algos.chase.iceberg import decide

        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            await boot.job._cancel_working()
            self.assertIsNone(boot.job.state.ledger.working())
            view = boot.job._market_view()
            params = boot.job.state.params
            assert view is not None and params is not None
            q = decide(params, view, boot.job.state.remaining)
            await boot.job._place_working(q)
        self.assertEqual(len(boot.orders.creates), 2)

    async def test_unpause_credits_trade_from_second_page(self) -> None:
        boot = boot_job()
        with patch_chase(boot.clock, boot.gateway, boot.orders):
            await boot.job._evaluate()
            coi = boot.orders.creates[0]["client_order_index"]
            await boot.job._evaluate()
            boot.orders.remove_by_coi(coi)
            await boot.job._evaluate()
            boot.clock.advance(MISSING_FILL_GRACE_MS + 1)
            await boot.job._evaluate()
            self.assertEqual(boot.job.state.status, ChaseStatus.ERROR)
            boot.orders.trades_pages = [
                [],
                [
                    trade_print(
                        market_index=1,
                        size="1",
                        price="99.96",
                        trade_id=42,
                        bid_client_id=coi,
                    )
                ],
            ]
            await boot.job.unpause()
        self.assertEqual(boot.job.state.status, ChaseStatus.RUNNING)
        self.assertEqual(boot.job.state.filled, D("1"))
        self.assertEqual(boot.job.state.remaining, D("9"))
        self.assertGreaterEqual(boot.orders.trades_calls, 2)

    async def test_credit_rest_trades_page_cap_fails_closed(self) -> None:
        boot = boot_job()
        boot.orders.trades_pages = [[], [], []]
        with (
            patch_chase(boot.clock, boot.gateway, boot.orders),
            patch(
                "mayedge.algos.chase.fills.REST_TRADES_MAX_PAGES",
                2,
            ),
        ):
            ok = await boot.job._credit_rest_trades()
        self.assertFalse(ok)
