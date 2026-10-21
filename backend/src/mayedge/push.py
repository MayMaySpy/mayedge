"""Telegram pushes. A push repeats a fact; it raises nothing and never blocks a trade.

The rules are docs/push-rules.md. The ``push:`` block in alerts.yaml is the source of truth.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import html
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from mayedge.config import settings
from mayedge.push_inbox import TelegramInbox
from mayedge.push_router import PushRouter, PushSink
from mayedge.push_settings import (
    Clock,
    PushSettings,
    _WallClock,
    load_push_settings,
    public_push_status,
    push_settings_from_dict,
)
from mayedge.push_text import boot_text, daily_journal_text, daily_text, freeze_text

logger = logging.getLogger(__name__)

# httpx logs the request URL at INFO, and that URL contains the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_MAX_CHARS = 4000
_PACE_S = 1.0
_FAIL_WAITS = (2.0, 4.0, 8.0)
_MAX_ATTEMPTS = 3
_MAX_429 = 8


@dataclass(frozen=True)
class SendResult:
    status_code: int
    retry_after: float | None = None


class Transport(Protocol):
    async def send_message(self, text: str) -> SendResult: ...


class HttpxTransport:
    """POST sendMessage. The token stays in the URL and is never logged."""

    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._client = client

    async def send_message(self, text: str) -> SendResult:
        response = await self._client.post(
            self._url,
            json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        retry_after = None
        if response.status_code == 429:
            try:
                retry_after = float(response.json()["parameters"]["retry_after"])
            except (KeyError, TypeError, ValueError):
                retry_after = 1.0
        return SendResult(response.status_code, retry_after)


@dataclass
class _Item:
    key: str
    text: str
    urgent: bool = False
    force: bool = False
    done: asyncio.Future[str | None] | None = None


class TelegramPusher:
    """Queue, pace, dedupe and digest. ``push`` returns immediately and never raises."""

    def __init__(
        self,
        *,
        enabled: bool,
        cfg: PushSettings | None = None,
        transport: Transport | None = None,
        clock: Clock | None = None,
        testnet: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.enabled = enabled
        self._cfg = cfg or PushSettings()
        self._transport = transport
        self._clock = clock or _WallClock()
        self._testnet = testnet
        self._client = client
        self._q: deque[_Item] = deque()
        self._held: list[_Item] = []
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None
        self._inbox_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._last_sent: dict[str, float] = {}
        self._queued: set[str] = set()
        self._window_start: float | None = None
        self._sent_in_window = 0
        self._last_mono: float | None = None
        self._router = PushRouter(
            self, self._cfg, self._clock, journal=journal_day_totals, portfolio=portfolio_day_totals
        )

    @classmethod
    def from_settings(cls) -> TelegramPusher:
        return cls(
            enabled=settings.push_enabled,
            cfg=load_push_settings(),
            testnet=settings.lighter_network.value == "testnet",
        )

    def on_desk_msg(self, msg: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self._router.on_message(msg)
        except Exception:
            logger.warning("push router failed")

    def status_text(self) -> str:
        """The answer to /status (push-rules, Commands)."""
        return self._router.status_text("testnet" if self._testnet else "mainnet")

    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None:
        try:
            self._enqueue(_Item(key=key, text=text, urgent=urgent, force=force or urgent))
        except Exception:
            logger.warning("push dropped before the queue")

    async def test_push(self) -> dict[str, Any]:
        if not self.enabled or self._task is None:
            return {"ok": False, "error": "Pushes are off"}
        loop = asyncio.get_running_loop()
        done: asyncio.Future[str | None] = loop.create_future()
        self._enqueue(
            _Item(key=f"test:{self._clock.mono()}", text="Desk test push ✓", urgent=True, done=done)
        )
        try:
            error = await asyncio.wait_for(done, timeout=30)
        except TimeoutError:
            return {"ok": False, "error": "Telegram did not answer"}
        if error:
            return {"ok": False, "error": error}
        return {"ok": True}

    async def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        inbox: TelegramInbox | None = None
        if self._transport is None:
            token = settings.telegram_bot_token or ""
            chat = settings.telegram_chat_id or ""
            self._client = httpx.AsyncClient(timeout=10)
            self._transport = HttpxTransport(token, chat, self._client)
            if self._cfg.commands == "status":
                inbox = TelegramInbox(
                    token=token,
                    chat_id=chat,
                    client=self._client,
                    answer=self.status_text,
                    send=lambda key, text: self.push(key, text, force=True),
                    now=self._clock.now,
                )
        self._stopped = False
        self._task = asyncio.create_task(self._run())
        if inbox is not None:
            self._inbox_task = asyncio.create_task(inbox.run())

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
        if self._inbox_task is not None:
            self._inbox_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._inbox_task
            self._inbox_task = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def settle(self) -> None:
        """Tests: wait until the queue and any digest have gone out."""
        if not self.enabled:
            return
        for _ in range(4000):
            if self._idle.is_set() and not self._q and not self._held:
                await asyncio.sleep(0)
                if self._idle.is_set() and not self._q and not self._held:
                    return
            await asyncio.sleep(0)
        raise TimeoutError("push worker did not settle")

    def _enqueue(self, item: _Item) -> None:
        if not self.enabled:
            if item.done is not None and not item.done.done():
                item.done.set_result("Pushes are off")
            return
        now = self._clock.mono()
        if not item.force and not item.urgent:
            last = self._last_sent.get(item.key)
            if last is not None and now - last < self._cfg.repeat_s:
                return
            if item.key in self._queued:
                return
        if item.urgent:
            insert_at = 0
            for existing in self._q:
                if not existing.urgent:
                    break
                insert_at += 1
            self._q.insert(insert_at, item)
        else:
            self._q.append(item)
        self._queued.add(item.key)
        self._idle.clear()
        self._wake.set()

    async def _run(self) -> None:
        try:
            while not self._stopped:
                self._router.poll()
                self._flush_window()
                item = self._next_item()
                if item is None:
                    await self._wait()
                    continue
                await self._pace()
                error = await self._deliver(item)
                self._queued.discard(item.key)
                if error is None:
                    self._note_sent(item)
                self._finish(item, error)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("push worker stopped")

    def _next_item(self) -> _Item | None:
        if not self._q:
            return None
        item = self._q[0]
        if item.urgent or item.force or self._under_cap():
            self._q.popleft()
            return item
        self._q.popleft()
        self._held.append(item)
        self._queued.discard(item.key)
        return self._next_item()

    def _under_cap(self) -> bool:
        if self._window_start is None:
            return True
        if self._clock.mono() - self._window_start >= 60:
            return True
        return self._sent_in_window < self._cfg.max_per_min

    def _flush_window(self) -> None:
        if self._window_start is None or not self._held:
            if self._window_start is not None and self._clock.mono() - self._window_start >= 60:
                self._window_start = None
                self._sent_in_window = 0
            return
        if self._clock.mono() - self._window_start < 60:
            return
        texts = [item.text for item in self._held]
        for item in self._held:
            self._last_sent[item.key] = self._clock.mono()
            self._finish(item, None)
        self._held.clear()
        self._window_start = None
        self._sent_in_window = 0
        digest = f"{len(texts)} more: " + "; ".join(texts)
        self._q.appendleft(_Item(key=f"digest:{self._clock.mono()}", text=digest, force=True))

    async def _wait(self) -> None:
        delay = self._wait_delay()
        self._wake.clear()
        if self._q or (delay is not None and delay <= 0):
            return
        self._idle.set()
        if delay is None:
            await self._wake.wait()
            self._idle.clear()
            return
        sleep_task = asyncio.create_task(self._clock.sleep(delay))
        wake_task = asyncio.create_task(self._wake.wait())
        _done, pending = await asyncio.wait(
            {sleep_task, wake_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._idle.clear()

    def _wait_delay(self) -> float | None:
        delay: float | None = None
        if self._held and self._window_start is not None:
            delay = max(0.0, self._window_start + 60 - self._clock.mono())
        soon = self._soonest_timer()
        if soon is None:
            return delay
        return soon if delay is None else min(delay, soon)

    def _soonest_timer(self) -> float | None:
        return self._router.due_in()

    async def _pace(self) -> None:
        if self._last_mono is None:
            return
        wait = _PACE_S - (self._clock.mono() - self._last_mono)
        if wait > 0:
            await self._clock.sleep(wait)

    async def _deliver(self, item: _Item) -> str | None:
        if self._transport is None:
            return "Pushes are off"
        text = self._format(item.text)
        waits = _FAIL_WAITS
        attempt = 0
        rate_limits = 0
        while True:
            try:
                result = await self._transport.send_message(text)
            except Exception:
                result = SendResult(0)
            if 200 <= result.status_code < 300:
                return None
            if result.status_code == 429 and rate_limits < _MAX_429:
                rate_limits += 1
                await self._clock.sleep(result.retry_after or 1)
                continue
            if attempt >= _MAX_ATTEMPTS - 1:
                await self._clock.sleep(waits[-1])
                logger.warning("push dropped after %s failures", _MAX_ATTEMPTS)
                return "Telegram did not accept the push"
            await self._clock.sleep(waits[attempt])
            attempt += 1

    def _note_sent(self, item: _Item) -> None:
        now = self._clock.mono()
        self._last_sent[item.key] = now
        self._last_mono = now
        if self._window_start is None or now - self._window_start >= 60:
            self._window_start = now
            self._sent_in_window = 0
        if not item.key.startswith("digest:"):
            self._sent_in_window += 1

    def _format(self, text: str) -> str:
        body = html.escape(text, quote=False)
        if self._testnet:
            body = f"[testnet] {body}"
        if len(body) > _MAX_CHARS:
            body = body[:_MAX_CHARS]
        return body

    @staticmethod
    def _finish(item: _Item, error: str | None) -> None:
        if item.done is not None and not item.done.done():
            item.done.set_result(error)


def portfolio_day_totals(day: str) -> dict[str, float] | None:
    """D1: each kind's change over the UTC day `day` (`YYYY-MM-DD`), or None without both midnights."""
    from mayedge.persist_portfolio import portfolio_buckets
    from mayedge.portfolio import utc_day_change

    start_ms = calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000
    change = utc_day_change(portfolio_buckets("1d", "pnl", start_ms), start_ms)
    if change is None:
        return None
    return {kind: float(value) for kind, value in change.items()}


def journal_day_totals(day: str) -> tuple[int, float, float, float]:
    """Closed Round trips whose UTC close date is `day` (`YYYY-MM-DD`)."""
    from mayedge.api.routes.journal import _trips
    from mayedge.journal import _group_key, summary

    chosen = [
        trip for trip in _trips() if trip.close_ts is not None and _group_key(trip, "day") == day
    ]
    rows = summary(chosen, "none")
    if not rows:
        return (0, 0.0, 0.0, 0.0)
    row = rows[0]
    return (row.count, float(row.net), float(row.fees), float(row.funding))


__all__ = [
    "Clock",
    "HttpxTransport",
    "PushRouter",
    "PushSettings",
    "PushSink",
    "SendResult",
    "TelegramPusher",
    "Transport",
    "boot_text",
    "daily_journal_text",
    "daily_text",
    "freeze_text",
    "journal_day_totals",
    "load_push_settings",
    "portfolio_day_totals",
    "public_push_status",
    "push_settings_from_dict",
]
