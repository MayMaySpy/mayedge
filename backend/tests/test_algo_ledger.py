from decimal import Decimal
from unittest import TestCase

from mayedge.algos.ledger import Ledger

D = Decimal


class LedgerTests(TestCase):
    def test_master_clip_and_partial_fill(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        self.assertEqual(clip.seq, 1)
        self.assertEqual(clip.status, "live")
        delta = led.apply_open(clip, D("0.4"), now=2, order_index=184291)
        self.assertEqual(delta, D("0.6"))
        self.assertEqual(clip.filled, D("0.6"))
        self.assertEqual(clip.order_index, 184291)
        self.assertEqual(len(led.fills), 1)
        self.assertEqual(led.fills[0].qty, D("0.6"))
        self.assertEqual(led.fills[0].order_index, 184291)

    def test_full_fill_when_clip_leaves_book(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.apply_open(clip, D("1"), now=2, order_index=1)
        delta = led.close_missing(clip, canceling=False, now=3)
        self.assertEqual(delta, D("1"))
        self.assertEqual(clip.status, "filled")
        self.assertEqual(led.fills[0].qty, D("1"))

    def test_unacked_clip_is_not_a_fill(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        delta = led.close_missing(clip, canceling=False, now=2)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.status, "live")
        self.assertEqual(led.fills, [])

    def test_cancel_does_not_fill_remainder(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.apply_open(clip, D("0.5"), now=2)
        delta = led.close_missing(clip, canceling=True, now=3)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(clip.filled, D("0.5"))
        self.assertEqual(len(led.fills), 1)

    def test_trade_credits_and_dedupes(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        d1 = led.apply_trade(clip, D("0.4"), now=2, trade_id=11, order_index=99)
        d2 = led.apply_trade(clip, D("0.4"), now=3, trade_id=11)
        self.assertEqual(d1, D("0.4"))
        self.assertEqual(d2, D("0"))
        self.assertEqual(clip.filled, D("0.4"))
        self.assertEqual(led.filled_total(), D("0.4"))

    def test_trade_does_not_double_count_open_sync(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.apply_open(clip, D("0.6"), now=2)  # filled 0.4 via book
        delta = led.apply_trade(clip, D("0.4"), now=3, trade_id=22)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.filled, D("0.4"))
        self.assertEqual(led.filled_total(), D("0.4"))

    def test_book_filled_drives_partial(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        delta = led.apply_open(clip, D("1"), now=2, book_filled=D("0.25"))
        self.assertEqual(delta, D("0.25"))
        self.assertEqual(clip.remaining, D("0.75"))

    def test_working_side_two_live_clips(self) -> None:
        led = Ledger()
        led.place(client_order_index=1, price=D("99"), qty=D("1"), now=1, side="buy")
        led.place(client_order_index=2, price=D("101"), qty=D("1"), now=2, side="sell")
        self.assertIsNotNone(led.working_side("buy"))
        self.assertIsNotNone(led.working_side("sell"))
        self.assertEqual(len(led.live_clips()), 2)

    def test_amend_keeps_clip_identity(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.apply_open(clip, D("0.4"), now=2, order_index=184291)
        led.amend(clip, price=D("99.95"), now=3)
        self.assertEqual(clip.seq, 1)
        self.assertEqual(clip.client_order_index, 8)
        self.assertEqual(clip.order_index, 184291)
        self.assertEqual(clip.price, D("99.95"))
        self.assertEqual(clip.filled, D("0.6"))
        self.assertEqual(clip.remaining, D("0.4"))
        self.assertEqual(clip.status, "live")
        self.assertEqual(clip.placed_at, 3)

    def test_replace_then_new_clip(self) -> None:
        led = Ledger()
        a = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.close_missing(a, canceling=True, now=2)
        b = led.place(client_order_index=9, price=D("99.95"), qty=D("1"), now=3)
        self.assertEqual(b.seq, 2)
        self.assertEqual(led.working(), b)
        self.assertEqual(a.status, "cancelled")

    def test_working_filled_total_caps_per_clip(self) -> None:
        led = Ledger()
        a = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        led.apply_open(a, D("0"), now=2, book_filled=D("3.5"))
        b = led.place(client_order_index=9, price=D("99.95"), qty=D("3.5"), now=3)
        led.apply_trade(b, D("1"), now=4, trade_id=1)
        self.assertEqual(led.working_filled_total(), D("4.5"))
        self.assertLessEqual(led.working_filled_total(), D("7"))

    def test_requote_cache_miss_without_trades_is_cancel(self) -> None:
        """Missing from book with no trade evidence must not invent a full fill."""
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        led.apply_open(clip, D("3.5"), now=2, order_index=1)  # ack only
        self.assertFalse(led.should_fill_when_missing(clip))
        delta = led.close_missing(clip, canceling=True, now=3)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(clip.filled, D("0"))
        self.assertEqual(led.working_filled_total(), D("0"))

    def test_partial_then_requote_miss_keeps_partial_only(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        led.apply_open(clip, D("2.5"), now=2)  # filled 1.0
        self.assertTrue(led.has_fill_evidence(clip))
        self.assertFalse(led.should_fill_when_missing(clip))
        led.close_missing(clip, canceling=True, now=3)
        self.assertEqual(clip.status, "cancelled")
        self.assertEqual(clip.filled, D("1"))
        self.assertEqual(led.working_filled_total(), D("1"))

    def test_full_trade_coverage_allows_fill_when_missing(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        led.apply_trade(clip, D("3.5"), now=2, trade_id=9)
        self.assertTrue(led.should_fill_when_missing(clip))
        self.assertEqual(clip.filled, D("3.5"))
        delta = led.close_missing(clip, canceling=False, now=3)
        self.assertEqual(delta, D("0"))  # already full
        self.assertEqual(clip.status, "filled")
        self.assertEqual(led.working_filled_total(), D("3.5"))

    def test_sustained_miss_credits_fill(self) -> None:
        """After grace, a vanished seen clip is filled (natural full fill)."""
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        led.apply_open(clip, D("3.5"), now=2, order_index=1)
        clip.missing_since = 1000
        self.assertFalse(led.should_fill_when_missing(clip))
        delta = led.close_missing(clip, canceling=False, now=3000)
        self.assertEqual(delta, D("3.5"))
        self.assertEqual(clip.status, "filled")
        self.assertEqual(led.working_filled_total(), D("3.5"))

    def test_missing_since_cleared_when_seen_again(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        clip.missing_since = 1000
        led.apply_open(clip, D("3.5"), now=2, order_index=1)
        self.assertIsNone(clip.missing_since)

    def test_heal_clip_filled_from_tape(self) -> None:
        """If fill events exist but clip.filled lagged, master progress still moves."""
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("3.5"), now=1)
        # Simulate a desync: tape has a fill, clip.filled was not updated.
        from mayedge.algos.ledger import Fill

        led.fills.append(
            Fill(
                seq=1,
                clip_seq=clip.seq,
                price=D("99.96"),
                qty=D("3.5"),
                ts=2,
                order_index=1,
                client_order_index=8,
            )
        )
        led.next_fill = 2
        self.assertEqual(clip.filled, D("0"))
        # Mimic runner heal
        by_seq = {}
        for f in led.fills:
            by_seq[f.clip_seq] = by_seq.get(f.clip_seq, D("0")) + f.qty
        for c in led.clips:
            taped = by_seq.get(c.seq, D("0"))
            if taped > c.filled:
                c.filled = min(c.qty, taped)
        self.assertEqual(led.working_filled_total(), D("3.5"))

    def test_find_clip_by_coi_and_order_index(self) -> None:
        led = Ledger()
        a = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1, order_index=10)
        b = led.place(client_order_index=9, price=D("99.95"), qty=D("1"), now=2, order_index=11)
        self.assertEqual(led.find_clip(client_order_index=8), a)
        self.assertEqual(led.find_clip(order_index=11), b)
        self.assertIsNone(led.find_clip(client_order_index=99))
        self.assertIsNone(led.find_clip(order_index=99))

    def test_apply_trade_zero_qty(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        delta = led.apply_trade(clip, D("0"), now=2)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.filled, D("0"))

    def test_apply_trade_without_trade_id(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        d1 = led.apply_trade(clip, D("0.3"), now=2)
        d2 = led.apply_trade(clip, D("0.2"), now=3)
        self.assertEqual(d1, D("0.3"))
        self.assertEqual(d2, D("0.2"))
        self.assertEqual(clip.filled, D("0.5"))

    def test_close_missing_already_closed(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.close_missing(clip, canceling=True, now=2)
        delta = led.close_missing(clip, canceling=False, now=3)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.status, "cancelled")

    def test_has_fill_evidence_via_trade_qty_when_filled_lagged(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.trade_qty_by_clip[clip.seq] = D("0.4")
        self.assertTrue(led.has_fill_evidence(clip))
        self.assertEqual(clip.filled, D("0"))

    def test_to_dict_shape(self) -> None:
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.apply_trade(clip, D("0.25"), now=2, trade_id=1)
        payload = led.to_dict()
        self.assertIn("clips", payload)
        self.assertIn("fills", payload)
        self.assertIn("working", payload)
        self.assertEqual(payload["working"]["client_order_index"], "8")
        self.assertEqual(len(payload["fills"]), 1)

    def test_trade_ahead_of_open_sync_watermark(self) -> None:
        """Trade credits first; later open sync must not double-count."""
        led = Ledger()
        clip = led.place(client_order_index=8, price=D("99.96"), qty=D("1"), now=1)
        led.apply_trade(clip, D("0.6"), now=2, trade_id=7)
        delta = led.apply_open(clip, D("0.4"), now=3, order_index=1)
        self.assertEqual(delta, D("0"))
        self.assertEqual(clip.filled, D("0.6"))
        self.assertEqual(led.filled_total(), D("0.6"))
