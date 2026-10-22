"""Checks Price alerts against the prices the desk already holds. No venue call, no order.

Rules: docs/idea-rules.md A5–A9, ADR 0021.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from mayedge.idea_alerts import (
    CHECK_S,
    alert_text,
    decimal_of,
    known,
    met,
    push_text,
    rearm_due,
)
from mayedge.ideas import last_text
from mayedge.lighter.gateway import gateway
from mayedge.numbers import fmt_decimal, parse_decimal
from mayedge.persist_idea_alerts import alert_auto_rearm, alert_fire, alerts_watched

logger = logging.getLogger(__name__)

Quote = Callable[[str], tuple[Decimal | None, Decimal | None]]
Emit = Callable[[dict[str, Any]], None]


def gateway_quote(symbol: str) -> tuple[Decimal | None, Decimal | None]:
    """L1's Last and the Daily Change, from the market the desk holds."""
    meta = gateway.get_market(symbol)
    if meta is None:
        return None, None
    last = last_text(meta.last_trade_price, meta.mark_price, meta.mid_price)
    return (parse_decimal(last) if last else None), decimal_of(meta.change_24h)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class IdeaAlertWatch:
    def __init__(
        self,
        emit: Emit,
        quote: Quote = gateway_quote,
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        self._emit = emit
        self._quote = quote
        self._now_ms = now_ms
        self._started = now_ms()
        self._seen: set[int] = set()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("price alert check failed")
            await asyncio.sleep(CHECK_S)

    async def tick(self) -> int:
        """One look at every watched alert. Returns how many fired."""
        alerts = await asyncio.to_thread(alerts_watched)
        fired = 0
        for alert in alerts:
            last, change = self._quote(alert.symbol)
            now = self._now_ms()
            if alert.status == "fired":
                armed = rearm_due(alert, now, last, change)
                if armed is not None:
                    await asyncio.to_thread(alert_auto_rearm, alert.id, armed, now)
                continue
            if not known(alert, last, change):
                continue
            first = alert.id not in self._seen
            self._seen.add(alert.id)
            if not met(alert, last, change):
                continue
            # A7: met at the first look, armed before this desk started.
            at_start = first and alert.armed_at < self._started
            line = alert_text(alert, last, change, at_start=at_start)
            last_str = fmt_decimal(last) if last is not None else None
            fires = await asyncio.to_thread(alert_fire, alert.id, last_str, line, now)
            if fires is None:
                continue
            fired += 1
            self._emit(
                {
                    "type": "idea_alert",
                    "key": f"idea-alert:{alert.id}:{fires}",
                    "idea_id": alert.idea_id,
                    "alert_id": alert.id,
                    "symbol": alert.symbol,
                    "text": push_text(line, alert.note),
                }
            )
        return fired


_watch: IdeaAlertWatch | None = None


def start(emit: Emit) -> IdeaAlertWatch:
    global _watch
    _watch = IdeaAlertWatch(emit)
    _watch.start()
    return _watch


async def stop() -> None:
    global _watch
    if _watch is not None:
        await _watch.stop()
        _watch = None
