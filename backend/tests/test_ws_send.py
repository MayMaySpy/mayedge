"""Closed client sockets must not log as subscribe_market / websocket errors."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from starlette.websockets import WebSocketDisconnect, WebSocketState

from mayedge.api.ws import send_json, ws_connected


class TestWsSend(unittest.IsolatedAsyncioTestCase):
    async def test_disconnected_raises_disconnect(self) -> None:
        ws = MagicMock()
        ws.client_state = WebSocketState.DISCONNECTED
        ws.application_state = WebSocketState.CONNECTED
        with self.assertRaises(WebSocketDisconnect):
            await send_json(ws, {"type": "init"})
        ws.send_json.assert_not_called()

    async def test_send_after_close_becomes_disconnect(self) -> None:
        ws = MagicMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.application_state = WebSocketState.CONNECTED
        ws.send_json = AsyncMock(
            side_effect=RuntimeError('Cannot call "send" once a close message has been sent.')
        )
        with self.assertRaises(WebSocketDisconnect):
            await send_json(ws, {"type": "candles"})

    def test_connected_true_only_when_both_sides_open(self) -> None:
        ws = MagicMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.application_state = WebSocketState.CONNECTED
        self.assertTrue(ws_connected(ws))
        ws.client_state = WebSocketState.DISCONNECTED
        self.assertFalse(ws_connected(ws))


if __name__ == "__main__":
    unittest.main()
