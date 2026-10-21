"""push-rules, Commands: /status from the configured chat, answered read-only."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

import httpx

from mayedge.push import PushRouter, PushSettings, push_settings_from_dict
from mayedge.push_inbox import OTHER_TEXT, STALE_S, TelegramInbox, command_of

CHAT = "4242"
NOW = 1_761_055_200.0  # 2025-10-21 14:00 UTC


def _update(update_id: int, text: str, *, chat: str = CHAT, sent: float = NOW) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {"chat": {"id": int(chat)}, "text": text, "date": int(sent)},
    }


class Clock:
    def now(self) -> float:
        return NOW

    def mono(self) -> float:
        return NOW

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)


class Sink:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None:
        self.sent.append((key, text))


class CommandTests(unittest.TestCase):
    def test_status_from_the_configured_chat(self) -> None:
        self.assertEqual(command_of(_update(1, "/status"), CHAT, NOW), "status")
        self.assertEqual(command_of(_update(1, "/status@mayedge_bot now"), CHAT, NOW), "status")

    def test_any_other_command_gets_the_refusal(self) -> None:
        self.assertEqual(command_of(_update(1, "/kill"), CHAT, NOW), "other")

    def test_other_chats_plain_text_and_stale_commands_are_ignored(self) -> None:
        self.assertIsNone(command_of(_update(1, "/status", chat="999"), CHAT, NOW))
        self.assertIsNone(command_of(_update(1, "hello"), CHAT, NOW))
        self.assertIsNone(command_of(_update(1, "/status", sent=NOW - STALE_S - 1), CHAT, NOW))
        self.assertIsNone(command_of({"update_id": 1}, CHAT, NOW))

    def test_commands_are_on_unless_turned_off(self) -> None:
        self.assertEqual(push_settings_from_dict({}).commands, "status")
        self.assertEqual(push_settings_from_dict({"push": {"commands": "off"}}).commands, "off")


class InboxTests(unittest.IsolatedAsyncioTestCase):
    def _inbox(self, client: httpx.AsyncClient, sent: list[tuple[str, str]]) -> TelegramInbox:
        return TelegramInbox(
            token="t",
            chat_id=CHAT,
            client=client,
            answer=lambda: "Desk status",
            send=lambda key, text: sent.append((key, text)),
            now=lambda: NOW,
        )

    async def test_a_poll_answers_and_moves_the_offset_past_every_update(self) -> None:
        seen: list[httpx.Request] = []

        def reply(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            updates = [_update(7, "/status"), _update(8, "/status", chat="1"), _update(9, "/kill")]
            return httpx.Response(200, json={"ok": True, "result": updates})

        sent: list[tuple[str, str]] = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            inbox = self._inbox(client, sent)
            await inbox.poll_once()
            await inbox.poll_once()
        self.assertEqual(sent[:2], [("status:7", "Desk status"), ("command:9", OTHER_TEXT)])
        self.assertNotIn("offset", dict(seen[0].url.params))
        self.assertEqual(seen[1].url.params["offset"], "10")

    async def test_a_second_reader_of_the_bot_is_an_error_not_an_answer(self) -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(409, json={"ok": False}))
        ) as client:
            with self.assertRaises(RuntimeError):
                await self._inbox(client, []).poll_once()


class StatusTextTests(unittest.TestCase):
    def test_status_names_positions_algos_auto_kill_and_the_venue(self) -> None:
        router = PushRouter(Sink(), PushSettings(), Clock())
        router.on_message(
            {
                "type": "account",
                "unrealized_pnl": "123.4",
                "positions": [
                    {"symbol": "ETH", "size": "1.5", "unrealized_pnl": "100"},
                    {"symbol": "BTC", "size": "-0.1", "unrealized_pnl": "23.4"},
                    {"symbol": "SOL", "size": "0"},
                ],
            }
        )
        router.on_message({"type": "feed_health", "account_ws": "live", "venue_down_since": 0})
        router.on_message({"type": "auto_kill", "armed": True, "loss_usd": 500, "profit_usd": 1000})
        self.assertEqual(
            router.status_text("mainnet"),
            "Desk status (mainnet), 14:00 UTC\n"
            "2 Positions open, uPnL +$123: ETH +1.5 (+$100), BTC −0.1 (+$23)\n"
            "No algos live\n"
            "Auto kill armed: floor −$500, target +$1,000",
        )

    def test_status_says_when_the_account_feed_is_not_live(self) -> None:
        router = PushRouter(Sink(), PushSettings(), Clock())
        text = router.status_text("testnet")
        self.assertIn("No Positions open", text)
        self.assertIn("Account feed not live", text)
        self.assertIn("Auto kill off", text)


if __name__ == "__main__":
    unittest.main()
