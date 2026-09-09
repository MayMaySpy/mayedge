"""Exchange market WS must subscribe the desk's active market after connect."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from mayedge.lighter.gateway import LighterGateway
from mayedge.lighter.market_ws import connect_and_stream
from mayedge.lighter.models import MarketMeta


class _FakeExchangeWs:
    """Async context manager that delays connect, then records outbound frames."""

    def __init__(self, connect_delay: float = 0.12) -> None:
        self.sent: list[dict] = []
        self._delay = connect_delay
        self._closed = asyncio.Event()

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        await self._closed.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self._closed.set()

    async def __aenter__(self) -> _FakeExchangeWs:
        await asyncio.sleep(self._delay)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._closed.set()


def _gw(*, current: int = 1) -> LighterGateway:
    gw = LighterGateway()
    btc = MarketMeta(1, "BTC", 2, 4, 0.001, 10.0, market_type="perp")
    lit = MarketMeta(120, "LIT", 5, 2, 3.5, 10.0, market_type="perp")
    gw._markets = {1: btc, 120: lit}
    gw._perp_by_symbol = {"BTC": 1, "LIT": 120}
    gw._symbol_to_index = {"BTC": 1, "LIT": 120}
    gw._current_market_index = current
    gw._books.set_current_market(current)
    return gw


def _order_book_subs(ws: _FakeExchangeWs) -> list[str]:
    return [m["channel"] for m in ws.sent if m.get("channel", "").startswith("order_book/")]


class TestConnectSubscribesActiveMarket(unittest.IsolatedAsyncioTestCase):
    async def test_desk_switch_during_connect_is_the_session_market(self) -> None:
        gw = _gw(current=1)
        fake = _FakeExchangeWs()
        with patch("mayedge.lighter.market_ws.websockets.connect", return_value=fake):
            task = asyncio.create_task(connect_and_stream(gw))
            await asyncio.sleep(0.04)
            self.assertIsNone(gw._ws)
            await gw.set_active_market(120)
            deadline = asyncio.get_event_loop().time() + 1.0
            while asyncio.get_event_loop().time() < deadline:
                if "order_book/120" in _order_book_subs(fake):
                    break
                await asyncio.sleep(0.02)
            else:
                self.fail(f"expected order_book/120, got {_order_book_subs(fake)}")
            self.assertNotIn("order_book/1", _order_book_subs(fake))
            await fake.close()
            await asyncio.wait_for(task, 1.0)

    async def test_wait_for_book_needs_socket_then_snapshot(self) -> None:
        gw = _gw(current=120)
        task = asyncio.create_task(gw.wait_for_book(120))
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        gw.bind_market_ws(object())
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        await gw._books.handle_message(
            {
                "type": "subscribed/order_book",
                "channel": "order_book:120",
                "order_book": {
                    "bids": [{"price": "1", "size": "2"}],
                    "asks": [{"price": "3", "size": "4"}],
                },
            }
        )
        self.assertTrue(await asyncio.wait_for(task, 0.5))


if __name__ == "__main__":
    unittest.main()
