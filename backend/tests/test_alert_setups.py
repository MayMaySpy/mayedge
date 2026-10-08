from __future__ import annotations

import unittest

from mayedge.alert_setups import FactorView, PriceContext, build_note, classify_setup

_UP = PriceContext(move_pct=1.2, move_sigma=3.0)
_FLAT = PriceContext(move_pct=0.02, move_sigma=0.2)


def _f(kind: str, direction: str, value: float = 1.0, score: float = 5.0) -> FactorView:
    return FactorView(kind, direction, value, score)


class ClassifySetupTest(unittest.TestCase):
    def test_table(self) -> None:
        cases: list[tuple[list[FactorView], PriceContext | None, str]] = [
            ([_f("price", "up"), _f("oi", "up")], None, "breakout_longs"),
            ([_f("price", "up"), _f("oi", "down")], None, "short_squeeze"),
            ([_f("price", "down"), _f("oi", "up")], None, "breakdown_shorts"),
            ([_f("price", "down"), _f("oi", "down")], None, "long_flush"),
            ([_f("price", "up")], None, "pump"),
            ([_f("price", "down")], None, "dump"),
            ([_f("liq_cluster", "down")], None, "long_flush"),
            ([_f("liq_cluster", "up")], None, "short_squeeze"),
            ([_f("volume", "up")], _FLAT, "absorption"),
            ([_f("volume", "up")], _UP, "vol_surge"),
            ([_f("volume", "up")], None, "vol_surge"),
            ([_f("premium", "up", 0.8)], _FLAT, "crowded_longs"),
            ([_f("funding", "down", -0.02)], _FLAT, "crowded_shorts"),
            ([_f("dislocation", "up", 90)], None, "mark_off_book"),
        ]
        for factors, ctx, want in cases:
            with self.subTest(want=want, kinds=[f.kind for f in factors]):
                self.assertEqual(classify_setup(factors, ctx), want)

    def test_note_is_short(self) -> None:
        note = build_note(
            "long_flush",
            [
                {"kind": "price", "value": -1.6},
                {"kind": "volume", "value": 6.8},
                {"kind": "liq_cluster", "value": 1_200_000},
            ],
        )
        self.assertEqual(note, "Long flush · Px -1.60% · Vol 6.8× · Liqs $1.2M")


if __name__ == "__main__":
    unittest.main()
