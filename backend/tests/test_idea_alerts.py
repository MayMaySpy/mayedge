"""Price alerts on an Idea. Prices are faked; nothing reaches the venue. docs/idea-rules.md A1–A11."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from mayedge import db as store
from mayedge.api import responses
from mayedge.api.app import create_app
from mayedge.config import settings
from mayedge.idea_alert_watch import IdeaAlertWatch
from mayedge.idea_alerts import (
    REPEAT_AFTER_MS,
    Alert,
    AlertSpec,
    alert_text,
    arm,
    met,
    plan_levels,
    rearm_due,
    spec_of,
)
from mayedge.ideas import Refusal, normalise
from mayedge.persist_idea_alerts import (
    alert_add,
    alert_fire,
    alerts_for,
    alerts_watched,
)
from mayedge.persist_ideas import idea_get, idea_insert, idea_status
from mayedge.push_router import PushRouter
from mayedge.push_settings import PushSettings, push_settings_from_dict

D = Decimal


def _alert(**over: Any) -> Alert:
    fields: dict[str, Any] = {
        "id": 1,
        "idea_id": "idea-1",
        "symbol": "ZRO",
        "kind": "level",
        "direction": "above",
        "price": "2.20",
        "pct": None,
        "base": None,
        "repeat": False,
        "label": "",
        "note": "",
        "status": "armed",
        "fires": 0,
        "armed_at": 0,
        "fired_at": None,
    }
    fields.update(over)
    return Alert(**fields)


def _spec(**over: Any) -> AlertSpec:
    got = spec_of({"kind": "level", "price": "2.20", **over})
    assert isinstance(got, AlertSpec)
    return got


class RuleTests(unittest.TestCase):
    def test_a_level_takes_its_direction_from_last(self) -> None:
        self.assertEqual(arm(_spec(), D("2.15"), None).direction, "above")
        self.assertEqual(arm(_spec(), D("2.25"), None).direction, "below")
        self.assertEqual(arm(_spec(direction="below"), None, None).direction, "below")
        self.assertTrue(met(_alert(), D("2.20"), None))
        self.assertFalse(met(_alert(), D("2.19"), None))
        self.assertTrue(met(_alert(direction="below"), D("2.20"), None))

    def test_a_level_at_last_is_refused(self) -> None:
        with self.assertRaises(Refusal) as at:
            arm(_spec(), D("2.20"), None)
        self.assertEqual(at.exception.field, "price")
        with self.assertRaises(Refusal) as blind:
            arm(_spec(), None, None)
        self.assertEqual(blind.exception.field, "direction")

    def test_a_move_is_measured_from_its_base(self) -> None:
        armed = arm(_spec(kind="move", pct="5", price=None), D("2.15"), None)
        self.assertEqual((armed.direction, armed.base), ("either", "2.15"))
        move = _alert(kind="move", direction="either", price=None, pct="5", base="2.15")
        self.assertTrue(met(move, D("2.2575"), None))
        self.assertTrue(met(move, D("2.0425"), None))
        self.assertFalse(met(move, D("2.25"), None))
        self.assertFalse(met(replace(move, direction="up"), D("2.04"), None))
        with self.assertRaises(Refusal):
            arm(_spec(kind="move", pct="5", price=None), None, None)
        self.assertIsInstance(spec_of({"kind": "move", "pct": "0"}), Refusal)
        self.assertIsInstance(spec_of({"kind": "move", "pct": "101"}), Refusal)

    def test_a_day_already_met_is_refused(self) -> None:
        day = _spec(kind="day", pct="10", price=None, direction="up")
        with self.assertRaises(Refusal) as late:
            arm(day, D("2"), D("12.3"))
        self.assertIn("+12.3%", late.exception.message)
        self.assertEqual(arm(day, D("2"), D("4")).direction, "up")
        alert = _alert(kind="day", direction="up", price=None, pct="10")
        self.assertTrue(met(alert, None, D("10")))
        self.assertFalse(met(alert, None, D("-15")))

    def test_an_alert_waits_without_a_last(self) -> None:
        self.assertFalse(met(_alert(), None, None))
        self.assertFalse(
            met(_alert(kind="day", pct="1", price=None, direction="either"), D("2"), None)
        )

    def test_rearm_takes_last_now(self) -> None:
        fired = _alert(status="fired", fired_at=0, repeat=True)
        armed = rearm_due(fired, REPEAT_AFTER_MS, D("2.30"), None)
        assert armed is not None
        self.assertEqual(armed.direction, "below")
        move = _alert(
            kind="move",
            direction="up",
            price=None,
            pct="5",
            base="2",
            status="fired",
            fired_at=0,
            repeat=True,
        )
        moved = rearm_due(move, REPEAT_AFTER_MS, D("2.1"), None)
        assert moved is not None
        self.assertEqual(moved.base, "2.1")

    def test_a_repeat_rearms_after_15_minutes(self) -> None:
        fired = _alert(status="fired", fired_at=1_000, repeat=True)
        self.assertIsNone(rearm_due(fired, 1_000 + REPEAT_AFTER_MS - 1, D("2.3"), None))
        self.assertIsNotNone(rearm_due(fired, 1_000 + REPEAT_AFTER_MS, D("2.3"), None))
        self.assertIsNone(rearm_due(fired, 1_000 + REPEAT_AFTER_MS, D("2.20"), None))
        self.assertIsNone(
            rearm_due(_alert(status="fired", fired_at=0), REPEAT_AFTER_MS, D("2.3"), None)
        )

    def test_a_day_rearms_back_inside(self) -> None:
        day = _alert(
            kind="day",
            direction="up",
            price=None,
            pct="10",
            status="fired",
            fired_at=0,
            repeat=True,
        )
        self.assertIsNone(rearm_due(day, REPEAT_AFTER_MS, D("2"), D("11")))
        self.assertIsNotNone(rearm_due(day, REPEAT_AFTER_MS, D("2"), D("9")))

    def test_plan_alerts_skip_prices_already_watched(self) -> None:
        levels = plan_levels("2.18", "2.20", "2.08", ["2.40", "2.51"], D("2.30"), {D("2.40")})
        self.assertEqual(levels, [("2.20", "Entry zone"), ("2.08", "Stop"), ("2.51", "T2")])
        inside = plan_levels("2.18", "2.20", "2.08", [], D("2.19"), set())
        self.assertEqual(inside, [("2.08", "Stop")])
        self.assertEqual(plan_levels("2.18", "2.20", "2.08", [], None, set()), [])

    def test_alert_note_is_trimmed(self) -> None:
        self.assertEqual(_spec(note="  unlock day  ").note, "unlock day")
        self.assertIsInstance(spec_of({"kind": "level", "price": "2", "note": "x" * 121}), Refusal)

    def test_texts(self) -> None:
        self.assertEqual(
            alert_text(_alert(price="2200.5", label="T1"), D("2201.25"), None),
            "ZRO above 2,200.5 · T1 · Last 2,201.25",
        )
        move = _alert(kind="move", direction="either", price=None, pct="5", base="2.15")
        self.assertEqual(
            alert_text(move, D("2.2579"), None),
            "ZRO moved +5.02% from 2.15 (alert ±5%) · Last 2.2579",
        )
        day = _alert(kind="day", direction="up", price=None, pct="10")
        self.assertEqual(
            alert_text(day, D("2.2"), D("10.4"), at_start=True),
            "ZRO Daily Change +10.4% (alert +10%) · Last 2.2 · met when the desk started",
        )


def _idea(**over: Any):
    body = {"symbol": "zro", "side": "long", "thesis": "Unlock overhang gone after the 20th."}
    body.update(over)
    got = normalise(body)
    assert not isinstance(got, Refusal)
    return got


class _DbCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "alerts.db")
        store.init_db()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old

    def _new_idea(self, **over: Any) -> str:
        made, _ = idea_insert(_idea(**over), "2.15", now=1_000)
        return str(made["id"])


class StoreTests(_DbCase):
    def test_an_idea_holds_at_most_20_alerts(self) -> None:
        idea_id = self._new_idea()
        for n in range(20):
            alert_add(idea_id, _spec(price=str(3 + n)), D("2"), None, now=2_000)
        with self.assertRaises(Refusal):
            alert_add(idea_id, _spec(price="40"), D("2"), None, now=2_000)

    def test_deleting_the_idea_deletes_its_alerts(self) -> None:
        idea_id = self._new_idea()
        alert_add(idea_id, _spec(), D("2"), None, now=2_000)
        with store._lock:
            conn = store._connect()
            conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
            conn.commit()
        self.assertEqual(alerts_for(idea_id), [])

    def test_alerts_on_a_closed_idea_wait(self) -> None:
        idea_id = self._new_idea()
        alert_add(idea_id, _spec(), D("2"), None, now=2_000)
        self.assertEqual(len(alerts_watched()), 1)
        idea_status(idea_id, "dropped", None, None, None)
        self.assertEqual(alerts_watched(), [])
        idea_status(idea_id, "watching", None, None, None)
        self.assertEqual(len(alerts_watched()), 1)

    def test_a_fire_is_logged_once(self) -> None:
        idea_id = self._new_idea()
        made = alert_add(idea_id, _spec(), D("2"), None, now=2_000)
        self.assertEqual(alert_fire(int(made["id"]), "2.21", "ZRO above 2.20", now=3_000), 1)
        self.assertIsNone(alert_fire(int(made["id"]), "2.21", "ZRO above 2.20", now=3_001))
        detail = idea_get(idea_id)
        assert detail is not None
        lines = [line for line in detail["log"] if line["kind"] == "alert"]
        self.assertEqual(
            [(line["body"], line["last"]) for line in lines], [("ZRO above 2.20", "2.21")]
        )


class WatchTests(_DbCase):
    async def test_a_fire_logs_and_emits_once(self) -> None:
        idea_id = self._new_idea()
        alert_add(
            idea_id,
            AlertSpec("level", None, "2.20", None, False, "unlock day", "T1"),
            D("2.15"),
            None,
            now=2_000,
        )
        sent: list[dict[str, Any]] = []
        prices = {"ZRO": (D("2.19"), None)}
        watch = IdeaAlertWatch(sent.append, quote=lambda s: prices[s], now_ms=lambda: 1_000)
        self.assertEqual(await watch.tick(), 0)
        prices["ZRO"] = (D("2.2034"), None)
        self.assertEqual(await watch.tick(), 1)
        self.assertEqual(await watch.tick(), 0)
        self.assertEqual(len(sent), 1)
        msg = sent[0]
        self.assertEqual(msg["type"], "idea_alert")
        self.assertTrue(msg["key"].endswith(":1"))
        self.assertEqual(msg["text"], "\U0001f514 ZRO above 2.20 · T1 · Last 2.2034\nunlock day")
        fired = alerts_for(idea_id)[0]
        self.assertEqual((fired["status"], fired["fired_last"]), ("fired", "2.2034"))

    async def test_an_alert_met_at_start_says_so(self) -> None:
        idea_id = self._new_idea()
        alert_add(idea_id, _spec(), D("2.15"), None, now=2_000)
        sent: list[dict[str, Any]] = []
        watch = IdeaAlertWatch(
            sent.append, quote=lambda _s: (D("2.30"), None), now_ms=lambda: 5_000
        )
        await watch.tick()
        self.assertIn("met when the desk started", sent[0]["text"])

    async def test_an_alert_set_after_start_does_not_say_so(self) -> None:
        sent: list[dict[str, Any]] = []
        watch = IdeaAlertWatch(
            sent.append, quote=lambda _s: (D("2.30"), None), now_ms=lambda: 1_000
        )
        idea_id = self._new_idea()
        alert_add(idea_id, _spec(), D("2.15"), None, now=2_000)
        await watch.tick()
        self.assertNotIn("desk started", sent[0]["text"])

    async def test_a_repeat_comes_back(self) -> None:
        idea_id = self._new_idea()
        alert_add(idea_id, _spec(repeat=True), D("2.15"), None, now=2_000)
        clock = {"now": 3_000}
        sent: list[dict[str, Any]] = []
        watch = IdeaAlertWatch(
            sent.append, quote=lambda _s: (D("2.30"), None), now_ms=lambda: clock["now"]
        )
        await watch.tick()
        clock["now"] += REPEAT_AFTER_MS
        await watch.tick()
        again = alerts_for(idea_id)[0]
        self.assertEqual((again["status"], again["direction"]), ("armed", "below"))
        self.assertEqual(len(sent), 1)

    async def test_the_watch_never_fires_without_a_last(self) -> None:
        idea_id = self._new_idea()
        alert_add(idea_id, _spec(), D("2.15"), None, now=2_000)
        sent: list[dict[str, Any]] = []
        watch = IdeaAlertWatch(sent.append, quote=lambda _s: (None, None), now_ms=lambda: 5_000)
        await watch.tick()
        self.assertEqual(sent, [])


class _Sink:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None:
        self.sent.append((key, text))


class _Clock:
    def now(self) -> float:
        return 1_700_000_000.0

    def mono(self) -> float:
        return 0.0

    async def sleep(self, seconds: float) -> None:
        return None


_PUSHED = {"type": "idea_alert", "key": "idea-alert:7:1", "text": "\U0001f514 ZRO above 2.20"}


class PushTests(unittest.TestCase):
    def test_a_price_alert_pushes(self) -> None:
        sink = _Sink()
        PushRouter(sink, PushSettings(), _Clock()).on_message(dict(_PUSHED))
        self.assertEqual(sink.sent, [("idea-alert:7:1", "\U0001f514 ZRO above 2.20")])

    def test_ideas_off_keeps_only_the_toast(self) -> None:
        sink = _Sink()
        PushRouter(sink, PushSettings(ideas="off"), _Clock()).on_message(dict(_PUSHED))
        self.assertEqual(sink.sent, [])

    def test_the_ideas_knob_reads_a_bare_off(self) -> None:
        self.assertEqual(push_settings_from_dict({"push": {"ideas": False}}).ideas, "off")
        self.assertEqual(push_settings_from_dict({"push": {"ideas": "on"}}).ideas, "on")
        self.assertEqual(push_settings_from_dict({}).ideas, "on")


def _meta(last: float | None = 2.15, change: float | None = 1.0):
    from mayedge.lighter.models import MarketMeta

    return MarketMeta(1, "ZRO", 4, 2, 0.1, 10.0, last_trade_price=last, change_24h=change)


class ApiTests(_DbCase):
    def _client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://localhost")

    async def test_alert_routes(self) -> None:
        with patch("mayedge.idea_alert_watch.gateway.get_market", return_value=_meta()):
            async with self._client() as client:
                made = await client.post(
                    "/api/ideas",
                    json={
                        "symbol": "zro",
                        "side": "long",
                        "thesis": "Unlock overhang gone after the 20th.",
                        "entry_low": "2.18",
                        "entry_high": "2.20",
                        "stop": "2.08",
                        "targets": [{"price": "2.40"}],
                    },
                )
                idea_id = made.json()["idea"]["id"]
                level = await client.post(
                    f"/api/ideas/{idea_id}/alerts", json={"kind": "level", "price": "2.50"}
                )
                self.assertEqual(level.status_code, 200)
                responses.IdeaAlertSaved.model_validate(level.json())
                self.assertEqual(level.json()["alert"]["direction"], "above")
                at = await client.post(
                    f"/api/ideas/{idea_id}/alerts", json={"kind": "level", "price": "2.15"}
                )
                self.assertEqual(at.status_code, 422)
                self.assertEqual(at.json()["detail"]["field"], "price")
                plan = await client.post(f"/api/ideas/{idea_id}/alerts/plan")
                self.assertEqual(
                    [(a["price"], a["label"]) for a in plan.json()["alerts"]],
                    [("2.18", "Entry zone"), ("2.08", "Stop"), ("2.40", "T1")],
                )
                again = await client.post(f"/api/ideas/{idea_id}/alerts/plan")
                self.assertEqual(again.json()["alerts"], [])
                listed = await client.get(f"/api/ideas/{idea_id}/alerts")
                responses.IdeaAlerts.model_validate(listed.json())
                self.assertEqual(len(listed.json()["alerts"]), 4)
                alert_id = level.json()["alert"]["id"]
                rearm = await client.post(f"/api/idea-alerts/{alert_id}/rearm")
                self.assertEqual(rearm.status_code, 200)
                gone = await client.delete(f"/api/idea-alerts/{alert_id}")
                self.assertEqual(gone.status_code, 204)
                missing = await client.delete(f"/api/idea-alerts/{alert_id}")
                self.assertEqual(missing.status_code, 404)
                nobody = await client.post(
                    "/api/ideas/idea-nope/alerts", json={"kind": "level", "price": "2"}
                )
                self.assertEqual(nobody.status_code, 404)


if __name__ == "__main__":
    unittest.main()
