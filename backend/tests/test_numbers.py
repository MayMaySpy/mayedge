from decimal import Decimal
from unittest import TestCase

from mayedge.numbers import check_notional, fmt_decimal, to_decimal, to_decimal_or


class CheckNotionalTests(TestCase):
    def test_under_cap_passes(self) -> None:
        check_notional(Decimal("10"), Decimal("100"), 50_000.0)

    def test_over_cap_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, r"exceeds limit"):
            check_notional(Decimal("1000"), Decimal("100"), 50_000.0)

    def test_no_cap_is_noop(self) -> None:
        check_notional(Decimal("1e9"), Decimal("100"), None)


class FmtDecimalTests(TestCase):
    def test_keeps_integer_trailing_zeros(self) -> None:
        # Regression: naive rstrip("0") turned 210 into "21".
        self.assertEqual(fmt_decimal(Decimal("210")), "210")
        self.assertEqual(fmt_decimal(Decimal("1000")), "1000")
        self.assertEqual(fmt_decimal(Decimal("200")), "200")

    def test_strips_fractional_trailing_zeros(self) -> None:
        self.assertEqual(fmt_decimal(Decimal("3.50")), "3.5")
        self.assertEqual(fmt_decimal(Decimal("3.500")), "3.5")
        self.assertEqual(fmt_decimal(Decimal("21.0")), "21")

    def test_none_and_zero(self) -> None:
        self.assertIsNone(fmt_decimal(None))
        self.assertEqual(fmt_decimal(Decimal("0")), "0")
        self.assertEqual(fmt_decimal(Decimal("0.00")), "0")


class ToDecimalTests(TestCase):
    def test_parses_a_number(self) -> None:
        self.assertEqual(to_decimal("1.5"), Decimal("1.5"))
        self.assertEqual(to_decimal(Decimal("2")), Decimal("2"))

    def test_none_and_garbage_raise(self) -> None:
        for raw in (None, "", "nope", True):
            with self.assertRaises(ValueError):
                to_decimal(raw)

    def test_or_uses_the_default(self) -> None:
        zero = Decimal("0")
        self.assertEqual(to_decimal_or(None, zero), zero)
        self.assertEqual(to_decimal_or("", zero), zero)
        self.assertEqual(to_decimal_or("nope", zero), zero)
        self.assertEqual(to_decimal_or("4.25", zero), Decimal("4.25"))
        self.assertIs(to_decimal_or("nope", zero), zero)
