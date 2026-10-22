"""Idea rules that do not need the route. docs/idea-rules.md."""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any

from mayedge import db as store
from mayedge.config import settings
from mayedge.ideas import (
    Clash,
    Idea,
    Refusal,
    Target,
    complete,
    computed,
    last_text,
    move,
    normalise,
    outcome_of,
    plan_diff,
    r_multiples,
    second_open,
)
from mayedge.persist_ideas import idea_get, idea_insert


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "symbol": "zro",
        "side": "long",
        "thesis": "Unlock overhang gone after the 20th.",
    }
    body.update(over)
    return body


def _idea(**over: Any) -> Idea:
    got = normalise(_body(**over))
    if isinstance(got, Refusal):
        raise AssertionError(f"{got.field}: {got.message}")
    return got


def _refused(field: str, **over: Any) -> Refusal:
    got = normalise(_body(**over))
    if not isinstance(got, Refusal):
        raise AssertionError(f"expected a refusal on {field}")
    if got.field != field:
        raise AssertionError(f"{got.field}: {got.message}")
    return got


class IdeaRuleTests(unittest.TestCase):
    def test_a_symbol_is_upper_case(self) -> None:
        self.assertEqual(_idea(symbol=" zro ").symbol, "ZRO")
        self.assertEqual(_refused("symbol", symbol="  ").field, "symbol")

    def test_an_idea_needs_a_thesis(self) -> None:
        self.assertIn("10", _refused("thesis", thesis="  too short ").message)
        self.assertEqual(len(_idea(thesis="1234567890").thesis), 10)

    def test_a_second_open_idea_on_a_market_warns(self) -> None:
        open_ideas = [Clash("idea-aaa", "ZRO", "long"), Clash("idea-bbb", "ZRO", "short")]
        clash = second_open(open_ideas, "zro", "long")
        self.assertIsNotNone(clash)
        assert clash is not None
        self.assertEqual(clash.id, "idea-aaa")
        other = second_open(open_ideas, "ZRO", "short")
        self.assertIsNotNone(other)
        assert other is not None
        self.assertEqual(other.id, "idea-bbb")
        self.assertIsNone(second_open(open_ideas, "TIA", "long"))

    def test_tags_are_normalised(self) -> None:
        idea = _idea(tags=[" AI ", "ai", "L2", ""])
        self.assertEqual(idea.tags, ("ai", "l2"))
        self.assertIn("8", _refused("tags", tags=[f"t{i}" for i in range(9)]).message)
        self.assertEqual(_refused("tags", tags=["x" * 25]).field, "tags")
        self.assertEqual(_idea(tags=["x" * 24]).tags, ("x" * 24,))

    def test_catalysts_sort_by_date(self) -> None:
        idea = _idea(
            catalysts=[
                {"text": "vote", "date": "2026-11-01"},
                {"text": "no date", "date": None},
                {"text": "unlock", "date": "2026-10-20"},
                {"text": "listing", "date": "2026-10-20"},
            ]
        )
        self.assertEqual(
            [(item.text, item.date) for item in idea.catalysts],
            [
                ("unlock", "2026-10-20"),
                ("listing", "2026-10-20"),
                ("vote", "2026-11-01"),
                ("no date", None),
            ],
        )
        self.assertEqual(_refused("catalysts", catalysts=[{"text": "x"}] * 13).field, "catalysts")
        self.assertEqual(
            _refused("catalysts.0", catalysts=[{"text": "y" * 121, "date": None}]).field,
            "catalysts.0",
        )
        self.assertEqual(
            _refused("catalysts.0", catalysts=[{"text": "vote", "date": "2026-02-31"}]).field,
            "catalysts.0",
        )

    def test_prices_round_trip_as_typed(self) -> None:
        idea = _idea(
            entry_low="2.30",
            entry_high="2.30",
            stop="2.08540",
            targets=[{"price": "2.40", "pct": "50"}],
        )
        self.assertEqual(idea.entry_low, "2.30")
        self.assertEqual(idea.stop, "2.08540")
        self.assertEqual(idea.targets[0].pct, "50")
        self.assertIsInstance(
            normalise(_body(entry_low=2.30, entry_high="2.30", stop="2.10")), Refusal
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(tmp.name) / "ideas.db")
        self.addCleanup(self._restore, old)
        saved, _warning = idea_insert(idea, None)
        self.assertEqual(saved["entry_low"], "2.30")
        self.assertEqual(saved["stop"], "2.08540")
        again = idea_get(saved["id"])
        self.assertIsNotNone(again)
        assert again is not None
        self.assertEqual(again["idea"]["entry_low"], "2.30")
        self.assertEqual(again["idea"]["targets"][0]["price"], "2.40")

    def _restore(self, old: str) -> None:
        store.close_db()
        settings.db_path = old

    def test_a_zone_is_low_then_high(self) -> None:
        self.assertEqual(_idea(entry_low="2.30", entry_high="2.30", stop="2.10").entry_low, "2.30")
        self.assertEqual(
            _idea(entry_low="2.30", entry_high="2.30", stop="2.10").entry_high,
            "2.30",
        )
        self.assertEqual(_refused("entry_high", entry_low="3", entry_high="2").field, "entry_high")
        self.assertEqual(_refused("entry_high", entry_low="2").field, "entry_high")
        self.assertEqual(_refused("stop", stop="0").field, "stop")
        self.assertIn(
            "4",
            _refused(
                "targets", targets=[{"price": "3"}] * 5, entry_low="1", entry_high="2"
            ).message,
        )

    def test_a_long_stop_sits_below_the_zone(self) -> None:
        self.assertEqual(
            _refused("stop", entry_low="2.18", entry_high="2.20", stop="2.18").field, "stop"
        )
        self.assertIn(
            "below", _refused("stop", entry_low="2.18", entry_high="2.20", stop="2.30").message
        )
        kept = _idea(entry_low="2.18", entry_high="2.20", stop="2.08")
        self.assertEqual(kept.stop, "2.08")
        self.assertEqual(
            _refused(
                "targets.0",
                entry_low="2.18",
                entry_high="2.20",
                stop="2.08",
                targets=[{"price": "2.20"}],
            ).field,
            "targets.0",
        )

    def test_a_short_target_sits_below_the_zone(self) -> None:
        self.assertEqual(
            _refused(
                "targets.0",
                side="short",
                entry_low="2.20",
                entry_high="2.40",
                stop="2.50",
                targets=[{"price": "2.20"}],
            ).field,
            "targets.0",
        )
        self.assertIn(
            "above",
            _refused(
                "stop", side="short", entry_low="2.20", entry_high="2.40", stop="2.40"
            ).message,
        )
        kept = _idea(
            side="short",
            entry_low="2.20",
            entry_high="2.40",
            stop="2.50",
            targets=[{"price": "2.00"}],
        )
        self.assertEqual(kept.targets[0].price, "2.00")

    def test_targets_are_measured_from_the_midpoint(self) -> None:
        idea = _idea(
            entry_low="2.18",
            entry_high="2.20",
            stop="2.08",
            targets=[{"price": "2.40"}],
        )
        numbers = computed(idea)
        self.assertEqual(numbers["plan_entry"], "2.19")
        self.assertEqual(numbers["r"], "0.11")
        self.assertEqual(numbers["r_multiples"], ["1.91"])
        wide = _idea(
            entry_low="2", entry_high="4", stop="1", targets=[{"price": "7"}, {"price": "5"}]
        )
        self.assertEqual(r_multiples(wide), [Decimal("2.00"), Decimal("1.00")])
        self.assertEqual(computed(wide)["r_multiples"], ["2.00", "1.00"])

    def test_target_shares_add_up_to_100_or_less(self) -> None:
        self.assertEqual(
            _idea(
                entry_low="2",
                entry_high="2",
                stop="1",
                targets=[{"price": "3", "pct": "60"}, {"price": "4", "pct": "40"}],
            ).targets,
            (Target("3", "60"), Target("4", "40")),
        )
        self.assertEqual(
            _refused(
                "targets",
                entry_low="2",
                entry_high="2",
                stop="1",
                targets=[{"price": "3", "pct": "60"}, {"price": "4", "pct": "50"}],
            ).field,
            "targets",
        )
        self.assertIsNone(
            _idea(entry_low="2", entry_high="2", stop="1", targets=[{"price": "3"}]).targets[0].pct
        )

    def test_a_plan_needs_a_zone_and_a_stop(self) -> None:
        self.assertFalse(complete(_idea()))
        self.assertFalse(complete(_idea(entry_low="2", entry_high="2")))
        self.assertFalse(complete(_idea(stop="1")))
        self.assertTrue(complete(_idea(entry_low="2", entry_high="2.2", stop="1")))
        bare = _idea()
        self.assertIsNone(computed(bare)["plan_entry"])
        self.assertIsNone(computed(bare)["r"])
        self.assertIsNone(computed(bare)["r_multiples"])
        zoned = _idea(entry_low="2", entry_high="2", stop="1")
        self.assertEqual(computed(zoned)["r_multiples"], [])

    def test_status_moves(self) -> None:
        allowed = {
            ("watching", "active"),
            ("watching", "dropped"),
            ("active", "closed"),
            ("active", "dropped"),
            ("closed", "watching"),
            ("dropped", "watching"),
        }
        for before, after in allowed:
            self.assertTrue(move(before, after), f"{before} → {after}")
        for before, after in (
            ("watching", "closed"),
            ("watching", "watching"),
            ("active", "watching"),
            ("closed", "active"),
            ("dropped", "closed"),
            ("closed", "dropped"),
        ):
            self.assertFalse(move(before, after), f"{before} → {after}")

    def test_plan_diff_names_what_moved(self) -> None:
        before = _idea(entry_low="2.30", entry_high="2.35", stop="2.08", trigger="4h close")
        after = _idea(entry_low="2.28", entry_high="2.33", stop="2.12", trigger="4h close")
        self.assertEqual(
            plan_diff(before, after),
            "Entry 2.30–2.35 → 2.28–2.33 · Stop 2.08 → 2.12",
        )
        self.assertEqual(plan_diff(before, before), "")
        cleared = _idea()
        self.assertEqual(
            plan_diff(before, cleared),
            "Entry 2.30–2.35 cleared · Stop 2.08 cleared · Trigger 4h close cleared",
        )

    def test_review_outcomes(self) -> None:
        self.assertIsNone(outcome_of(None))
        for name in ("worked", "failed", "missed", "wrong"):
            self.assertEqual(outcome_of(name), name)
        with self.assertRaises(Refusal) as caught:
            outcome_of("nope")
        self.assertEqual(caught.exception.field, "outcome")

    def test_last_is_the_trade_else_the_mark_else_the_mid(self) -> None:
        self.assertEqual(last_text(2.5, 3.5, 4), "2.5")
        self.assertEqual(last_text(None, 3.5, 4), "3.5")
        self.assertEqual(last_text(0, 0, 4), "4")
        self.assertIsNone(last_text(None, None, None))
        self.assertIsNone(last_text(0, None, None))

    def test_a_new_idea_defaults_conviction_and_horizon(self) -> None:
        idea = _idea()
        self.assertEqual(idea.conviction, 2)
        self.assertEqual(idea.horizon, "swing")
        self.assertEqual(_refused("conviction", conviction=4).field, "conviction")
        self.assertEqual(_refused("horizon", horizon="forever").field, "horizon")
