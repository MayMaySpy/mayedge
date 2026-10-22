"""Idea routes. The gateway is faked; nothing is sent to the venue. docs/idea-rules.md."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from mayedge import db as store
from mayedge.api import responses
from mayedge.api.app import create_app
from mayedge.config import settings
from mayedge.lighter.models import MarketMeta


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "symbol": "zro",
        "side": "long",
        "thesis": "Unlock overhang gone after the 20th.",
    }
    body.update(over)
    return body


def _meta(last: float | None = 2.5) -> MarketMeta:
    return MarketMeta(
        1,
        "ZRO",
        4,
        2,
        0.1,
        10.0,
        last_trade_price=last,
        mark_price=9,
        mid_price=8,
    )


class IdeasApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "ideas.db")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old

    def _client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://localhost")

    async def test_an_unlisted_market_keeps_its_idea(self) -> None:
        with patch("mayedge.api.routes.ideas.gateway.get_market", return_value=None):
            async with self._client() as client:
                made = await client.post(
                    "/api/ideas", json=_body(symbol="gone", entry_low="2", entry_high="2", stop="1")
                )
                self.assertEqual(made.status_code, 200)
                idea = made.json()["idea"]
                self.assertEqual(idea["symbol"], "GONE")
                self.assertEqual(idea["status"], "watching")
                got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["idea"]["symbol"], "GONE")
        self.assertIsNone(got.json()["log"][0]["last"])

    async def test_a_new_idea_is_watching(self) -> None:
        async with self._client() as client:
            res = await client.post("/api/ideas", json=_body(symbol="zro"))
        self.assertEqual(res.status_code, 200)
        responses.IdeaCreated.model_validate(res.json())
        idea = res.json()["idea"]
        self.assertEqual(idea["status"], "watching")
        self.assertEqual(idea["conviction"], 2)
        self.assertEqual(idea["horizon"], "swing")
        self.assertEqual(idea["symbol"], "ZRO")
        self.assertIsNone(res.json()["warning"])
        self.assertTrue(idea["id"].startswith("idea-"))

    async def test_create_warns_about_a_second_open_idea(self) -> None:
        async with self._client() as client:
            first = await client.post("/api/ideas", json=_body())
            second = await client.post(
                "/api/ideas", json=_body(thesis="A second long, still after the unlock.")
            )
            other = await client.post(
                "/api/ideas", json=_body(side="short", thesis="The unlock is still ahead of us.")
            )
        self.assertIsNone(first.json()["warning"])
        warning = second.json()["warning"]
        self.assertEqual(warning["id"], first.json()["idea"]["id"])
        self.assertIn("ZRO long", warning["message"])
        self.assertEqual(second.status_code, 200)
        self.assertIsNone(other.json()["warning"])

    async def test_list_filters_and_reads_newest_first(self) -> None:
        async with self._client() as client:
            first = (await client.post("/api/ideas", json=_body(symbol="tia"))).json()["idea"]
            second = (await client.post("/api/ideas", json=_body())).json()["idea"]
            await client.post(
                f"/api/ideas/{first['id']}/status",
                json={"status": "dropped"},
            )
            listed = await client.get("/api/ideas")
            closed = await client.get("/api/ideas?status=dropped")
            everything = await client.get("/api/ideas?status=all")
            bad = await client.get("/api/ideas?status=nope")
        responses.Ideas.model_validate(listed.json())
        self.assertEqual([row["id"] for row in listed.json()["ideas"]], [second["id"]])
        self.assertEqual(closed.json()["ideas"][0]["id"], first["id"])
        self.assertEqual(len(everything.json()["ideas"]), 2)
        self.assertEqual(bad.status_code, 400)

    async def test_a_plan_change_is_logged(self) -> None:
        with patch("mayedge.api.routes.ideas.gateway.get_market", return_value=_meta()):
            async with self._client() as client:
                made = await client.post("/api/ideas", json=_body())
                idea = made.json()["idea"]
                patched = await client.patch(
                    f"/api/ideas/{idea['id']}",
                    json={
                        "seen_updated_at": idea["updated_at"],
                        "entry_low": "2.30",
                        "entry_high": "2.35",
                        "stop": "2.08",
                    },
                )
                got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(patched.status_code, 200)
        responses.IdeaSaved.model_validate(patched.json())
        self.assertEqual(patched.json()["idea"]["entry_low"], "2.30")
        self.assertEqual(patched.json()["idea"]["status"], "watching")
        log = got.json()["log"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["kind"], "plan")
        self.assertEqual(log[0]["body"], "Entry 2.30–2.35 · Stop 2.08")
        self.assertEqual(log[0]["last"], "2.5")

    async def test_a_status_move_is_one_log_line(self) -> None:
        with patch("mayedge.api.routes.ideas.gateway.get_market", return_value=_meta()):
            async with self._client() as client:
                idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
                moved = await client.post(
                    f"/api/ideas/{idea['id']}/status", json={"status": "active"}
                )
                got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["idea"]["status"], "active")
        log = got.json()["log"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["kind"], "status")
        self.assertEqual(log[0]["body"], "Watching → Active")
        self.assertEqual(log[0]["last"], "2.5")

    async def test_price_never_moves_a_status(self) -> None:
        async with self._client() as client:
            idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
            patched = await client.patch(
                f"/api/ideas/{idea['id']}",
                json={
                    "seen_updated_at": idea["updated_at"],
                    "entry_low": "2",
                    "entry_high": "2.2",
                    "stop": "1.5",
                },
            )
        self.assertEqual(patched.json()["idea"]["status"], "watching")

    async def test_a_bad_status_move_is_409(self) -> None:
        async with self._client() as client:
            idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
            moved = await client.post(f"/api/ideas/{idea['id']}/status", json={"status": "closed"})
            got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(moved.status_code, 409)
        self.assertEqual(got.json()["idea"]["status"], "watching")
        self.assertEqual(got.json()["log"], [])

    async def test_a_stale_patch_is_409(self) -> None:
        async with self._client() as client:
            idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
            stale = await client.patch(
                f"/api/ideas/{idea['id']}",
                json={
                    "seen_updated_at": idea["updated_at"] - 1,
                    "thesis": "This write lost the race, so it stays.",
                },
            )
            got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["message"], "Changed elsewhere, reloaded")
        self.assertEqual(got.json()["idea"]["thesis"], idea["thesis"])

    async def test_a_review_is_optional(self) -> None:
        async with self._client() as client:
            idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
            await client.post(f"/api/ideas/{idea['id']}/status", json={"status": "active"})
            closed = await client.post(f"/api/ideas/{idea['id']}/status", json={"status": "closed"})
            self.assertIsNone(closed.json()["idea"]["outcome"])
            self.assertEqual(closed.json()["idea"]["review"], "")
            self.assertIsNotNone(closed.json()["idea"]["closed_at"])
            reviewed = await client.patch(
                f"/api/ideas/{idea['id']}/review",
                json={"outcome": "missed", "review": "It went without us."},
            )
            reopened = await client.post(
                f"/api/ideas/{idea['id']}/status", json={"status": "watching"}
            )
        responses.IdeaSaved.model_validate(reviewed.json())
        self.assertEqual(reviewed.json()["idea"]["outcome"], "missed")
        again = reopened.json()["idea"]
        self.assertEqual(again["status"], "watching")
        self.assertIsNone(again["closed_at"])
        self.assertEqual(again["outcome"], "missed")
        self.assertEqual(again["review"], "It went without us.")

    async def test_refuses_name_the_field(self) -> None:
        async with self._client() as client:
            short = await client.post("/api/ideas", json=_body(thesis="nope"))
            zone = await client.post(
                "/api/ideas",
                json=_body(entry_low="2", entry_high="2.2", stop="3"),
            )
            shares = await client.post(
                "/api/ideas",
                json=_body(
                    entry_low="2",
                    entry_high="2",
                    stop="1",
                    targets=[{"price": "3", "pct": "60"}, {"price": "4", "pct": "50"}],
                ),
            )
        self.assertEqual(short.status_code, 422)
        self.assertEqual(short.json()["detail"]["field"], "thesis")
        self.assertEqual(zone.json()["detail"]["field"], "stop")
        self.assertIn("below", zone.json()["detail"]["message"])
        self.assertEqual(shares.json()["detail"]["field"], "targets")

    async def test_log_review_and_get(self) -> None:
        with patch("mayedge.api.routes.ideas.gateway.get_market", return_value=_meta(4)):
            async with self._client() as client:
                idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
                noted = await client.post(
                    f"/api/ideas/{idea['id']}/log", json={"body": "  Funding flipped.  "}
                )
                empty = await client.post(f"/api/ideas/{idea['id']}/log", json={"body": "  "})
                missing = await client.get("/api/ideas/idea-missing")
        self.assertEqual(noted.status_code, 200)
        responses.IdeaLogged.model_validate(noted.json())
        self.assertEqual(noted.json()["line"]["body"], "Funding flipped.")
        self.assertEqual(noted.json()["line"]["kind"], "update")
        self.assertEqual(noted.json()["line"]["last"], "4")
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(missing.status_code, 404)

    async def test_a_planner_start_marks_the_idea_active(self) -> None:
        with patch("mayedge.api.routes.ideas.gateway.get_market", return_value=_meta()):
            async with self._client() as client:
                idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
                started = await client.post(
                    f"/api/ideas/{idea['id']}/planner", json={"algo_id": "PL-1"}
                )
                again = await client.post(
                    f"/api/ideas/{idea['id']}/planner", json={"algo_id": "PL-1"}
                )
                second = await client.post(
                    f"/api/ideas/{idea['id']}/planner", json={"algo_id": "PL-2"}
                )
                got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(started.json()["idea"]["status"], "active")
        self.assertEqual(started.json()["idea"]["planner_ids"], ["PL-1"])
        self.assertEqual(again.json()["idea"]["planner_ids"], ["PL-1"])
        self.assertEqual(again.json()["idea"]["updated_at"], started.json()["idea"]["updated_at"])
        self.assertEqual(second.json()["idea"]["planner_ids"], ["PL-1", "PL-2"])
        log = got.json()["log"]
        self.assertEqual(
            [line["body"] for line in log],
            ["Planner PL-2", "Watching → Active · Planner PL-1"],
        )
        self.assertEqual({line["kind"] for line in log}, {"planner"})

    async def test_a_planner_on_a_closed_idea_is_refused(self) -> None:
        async with self._client() as client:
            idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
            await client.post(f"/api/ideas/{idea['id']}/status", json={"status": "dropped"})
            started = await client.post(
                f"/api/ideas/{idea['id']}/planner", json={"algo_id": "PL-9"}
            )
            got = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(started.status_code, 409)
        self.assertEqual(got.json()["idea"]["status"], "dropped")
        self.assertEqual(got.json()["idea"]["planner_ids"], [])

    async def test_delete_removes_the_log(self) -> None:
        async with self._client() as client:
            idea = (await client.post("/api/ideas", json=_body())).json()["idea"]
            await client.post(
                f"/api/ideas/{idea['id']}/log", json={"body": "A line that should go."}
            )
            removed = await client.delete(f"/api/ideas/{idea['id']}")
            missing = await client.get(f"/api/ideas/{idea['id']}")
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(missing.status_code, 404)
        store.init_db()
        with store._lock:
            conn = store._connect()
            ideas = conn.execute("SELECT COUNT(*) FROM ideas").fetchone()
            log = conn.execute("SELECT COUNT(*) FROM idea_log").fetchone()
        self.assertEqual(int(ideas[0]), 0)
        self.assertEqual(int(log[0]), 0)
