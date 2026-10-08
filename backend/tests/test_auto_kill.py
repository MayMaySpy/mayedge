from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge.api.app import create_app
from mayedge.auto_kill import (
    AutoKill,
    AutoKillConfig,
    breach,
    live_upnl,
    load_auto_kill,
    save_auto_kill,
)
from mayedge.kill import KillResult
from mayedge.lighter.models import Position


class LiveUpnlTests(unittest.TestCase):
    def test_long_and_short(self) -> None:
        long_pos = Position(
            market_index=1,
            symbol="BTC",
            size="2",
            entry_price="100",
            mark_price="110",
            unrealized_pnl="0",
            leverage=5,
            margin_mode="cross",
        )
        short_pos = Position(
            market_index=2,
            symbol="ETH",
            size="-1",
            entry_price="50",
            mark_price="45",
            unrealized_pnl="0",
            leverage=5,
            margin_mode="cross",
        )
        self.assertEqual(live_upnl([long_pos]), 20.0)
        self.assertEqual(live_upnl([short_pos]), 5.0)

    def test_fallback_to_venue_pnl(self) -> None:
        pos = Position(
            market_index=1,
            symbol="BTC",
            size="1",
            entry_price="0",
            mark_price="0",
            unrealized_pnl="-12.5",
            leverage=5,
            margin_mode="cross",
        )
        self.assertEqual(live_upnl([pos]), -12.5)


class BreachTests(unittest.TestCase):
    def test_loss_and_profit(self) -> None:
        cfg = AutoKillConfig(armed=True, loss_usd=500, profit_usd=1000)
        self.assertEqual(breach(-500, cfg), "loss")
        self.assertEqual(breach(-501, cfg), "loss")
        self.assertEqual(breach(1000, cfg), "profit")
        self.assertIsNone(breach(-100, cfg))


class AutoKillPersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auto_kill.json"
            from mayedge.auto_kill import AutoKillState

            state = AutoKillState(
                config=AutoKillConfig(armed=True, loss_usd=250, profit_usd=None),
                fired_at=123,
                fired_reason="loss",
                fired_upnl=-300,
                last_kill_status="killed",
            )
            save_auto_kill(state, path)
            loaded = load_auto_kill(path)
            self.assertTrue(loaded.config.armed)
            self.assertEqual(loaded.config.loss_usd, 250)
            self.assertEqual(loaded.fired_reason, "loss")


class AutoKillClassTests(unittest.IsolatedAsyncioTestCase):
    async def test_fires_once_and_disarms_before_kill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auto_kill.json"
            ak = AutoKill(path)
            run_kill = AsyncMock(
                return_value=KillResult(
                    status="killed", cancel_ok=True, cancel_error=None, flatten=[]
                )
            )
            emitted: list[dict] = []
            ak.start(run_kill=run_kill, emit=emitted.append)
            ak.configure(armed=True, loss_usd=100, profit_usd=None, current_positions=[])

            msg = {
                "type": "account",
                "positions": [
                    {
                        "size": "2",
                        "entry_price": "100",
                        "mark_price": "50",
                        "unrealized_pnl": "-50",
                    }
                ],
            }
            ak.on_gateway(msg)
            ak.on_gateway(msg)
            import asyncio

            await asyncio.sleep(0.05)

            run_kill.assert_awaited_once()
            self.assertFalse(ak.view()["armed"])
            on_disk = json.loads(path.read_text())
            self.assertFalse(on_disk["config"]["armed"])

    def test_arm_rejects_already_breached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ak = AutoKill(Path(tmp) / "auto_kill.json")
            ak.start(run_kill=AsyncMock(), emit=lambda _: None)
            with self.assertRaises(ValueError):
                ak.configure(
                    armed=True,
                    loss_usd=40,
                    profit_usd=None,
                    current_positions=[
                        {
                            "size": "1",
                            "entry_price": "100",
                            "mark_price": "50",
                            "unrealized_pnl": "-50",
                        }
                    ],
                )


class AutoKillEndpointTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.auto_kill")
    async def test_get_and_put(self, auto_kill_mock) -> None:
        auto_kill_mock.view.return_value = {"type": "auto_kill", "armed": False}
        auto_kill_mock.configure.return_value = {"type": "auto_kill", "armed": True}

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/kill/auto")
            self.assertEqual(res.status_code, 200)

        with patch("mayedge.api.app.order_service") as order_svc:
            order_svc.enabled = True
            app = create_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.put(
                    "/api/kill/auto",
                    json={"armed": True, "loss_usd": 500, "profit_usd": None},
                )
            self.assertEqual(res.status_code, 200)
            auto_kill_mock.configure.assert_called_once()
