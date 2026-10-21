"""The bot's inbox: answers /status from the configured chat, and nothing else.

Long polling of `getUpdates`, never a webhook: the desk opens no ingress (ADR 0005,
ADR 0017). An answer goes out through the pusher's queue like any push. Nothing here
places, amends or cancels an order. The rules are docs/push-rules.md, Commands.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Literal

import httpx

from mayedge.rows import is_list, is_obj, obj

logger = logging.getLogger(__name__)

# A command older than this was sent while the desk was down; its answer would mislead.
STALE_S = 120.0
_POLL_S = 50
_WAITS = (5.0, 15.0, 60.0)

Command = Literal["status", "other"]

OTHER_TEXT = "Only /status is answered here. The desk takes no orders from Telegram."


def command_of(update: object, chat_id: str, now_s: float) -> Command | None:
    """What an update asks, when it is a fresh command from the configured chat."""
    message = obj(obj(update).get("message"))
    if str(obj(message.get("chat")).get("id") or "") != chat_id:
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.startswith("/"):
        return None
    try:
        sent = float(message.get("date") or 0)
    except (TypeError, ValueError):
        return None
    if now_s - sent > STALE_S:
        return None
    word = text.split()[0].split("@", 1)[0].lower()
    return "status" if word == "/status" else "other"


class TelegramInbox:
    def __init__(
        self,
        *,
        token: str,
        chat_id: str,
        client: httpx.AsyncClient,
        answer: Callable[[], str],
        send: Callable[[str, str], None],
        now: Callable[[], float],
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._url = f"https://api.telegram.org/bot{token}/getUpdates"
        self._chat_id = chat_id
        self._client = client
        self._answer = answer
        self._send = send
        self._now = now
        self._sleep = sleep
        self._offset: int | None = None
        self._failures = 0

    def handle(self, updates: list[Any]) -> None:
        for update in updates:
            row = obj(update)
            try:
                update_id = int(row.get("update_id") or 0)
            except (TypeError, ValueError):
                continue
            self._offset = max(self._offset or 0, update_id + 1)
            asked = command_of(row, self._chat_id, self._now())
            if asked == "status":
                self._send(f"status:{update_id}", self._answer())
            elif asked == "other":
                self._send(f"command:{update_id}", OTHER_TEXT)

    async def poll_once(self) -> None:
        params: dict[str, Any] = {"timeout": _POLL_S, "allowed_updates": '["message"]'}
        if self._offset is not None:
            params["offset"] = self._offset
        response = await self._client.get(self._url, params=params, timeout=_POLL_S + 10)
        if response.status_code == 409:
            # Another reader of this bot (a second desk, or a webhook) holds getUpdates.
            raise RuntimeError("another reader holds this bot's updates")
        response.raise_for_status()
        body = response.json()
        result = body.get("result") if is_obj(body) else None
        self.handle(result if is_list(result) else [])

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
                self._failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                wait = _WAITS[min(self._failures, len(_WAITS) - 1)]
                if self._failures == 0:
                    # The URL holds the token; log the kind of failure only.
                    logger.warning("telegram inbox: %s; retrying in %.0fs", type(e).__name__, wait)
                self._failures += 1
                await self._sleep(wait)
