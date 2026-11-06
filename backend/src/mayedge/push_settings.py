"""The push: block of alerts.yaml, and the clock pushes run on."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import yaml

from mayedge.alerts import resolve_alerts_config_path
from mayedge.config import settings
from mayedge.push_text import _daily_at, _f

logger = logging.getLogger(__name__)


class Clock(Protocol):
    def now(self) -> float: ...

    def mono(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class _WallClock:
    def now(self) -> float:
        return time.time()

    def mono(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass
class PushSettings:
    alerts: str = "held"
    algos: str = "lifecycle"
    venue_down_after_s: float = 60
    account_stale_after_s: float = 120
    down_after_s: float = 60
    repeat_s: float = 600
    max_per_min: int = 12
    # HH:MM UTC for yesterday's journal. Empty is off.
    daily_at: str = ""
    # Commands the bot answers from the configured chat: status (read-only /status) or off.
    commands: str = "status"
    # Whether a fired Price alert also pushes: on or off (docs/push-rules.md).
    ideas: str = "on"
    # The Position watch (docs/position-rules.md): on or off, and its knobs.
    positions: str = "on"
    no_stop_after_s: float = 300
    bleed_r: float = 0.25
    brief_at: str = "07:00"


def push_settings_from_dict(data: dict[str, Any] | None) -> PushSettings:
    raw = (data or {}).get("push") or {}
    if not isinstance(raw, dict):
        raw = {}
    base = PushSettings()
    alerts = str(raw.get("alerts") or base.alerts)
    if alerts not in {"held", "urgent", "all", "off"}:
        alerts = base.alerts
    algos = str(raw.get("algos") or base.algos)
    if algos not in {"errors", "lifecycle"}:
        algos = base.algos
    return PushSettings(
        alerts=alerts,
        algos=algos,
        venue_down_after_s=_f(raw.get("venue_down_after_s"), base.venue_down_after_s),
        account_stale_after_s=_f(raw.get("account_stale_after_s"), base.account_stale_after_s),
        down_after_s=_f(raw.get("down_after_s"), base.down_after_s),
        repeat_s=_f(raw.get("repeat_s"), base.repeat_s),
        max_per_min=max(1, int(_f(raw.get("max_per_min"), base.max_per_min))),
        daily_at=_daily_at(raw.get("daily_at")),
        commands="off" if str(raw.get("commands") or base.commands) == "off" else "status",
        # YAML reads a bare off as False.
        ideas="off" if raw.get("ideas") in (False, "off") else "on",
        positions="off" if raw.get("positions") in (False, "off") else "on",
        no_stop_after_s=_f(raw.get("no_stop_after_s"), base.no_stop_after_s),
        bleed_r=_f(raw.get("bleed_r"), base.bleed_r),
        # An empty brief_at is off; a missing one keeps the default.
        brief_at=_daily_at(raw["brief_at"]) if "brief_at" in raw else base.brief_at,
    )


def load_push_settings() -> PushSettings:
    path = resolve_alerts_config_path()
    if not path.is_file():
        return PushSettings()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("push settings unreadable at %s; using defaults", path)
        return PushSettings()
    if not isinstance(data, dict):
        return PushSettings()
    return push_settings_from_dict(data)


def public_push_status() -> dict[str, Any]:
    """What the panel may see. Never the token or the chat id."""
    cfg = load_push_settings()
    return {
        "enabled": settings.push_enabled,
        "chat_set": bool(settings.telegram_chat_id),
        "alerts": cfg.alerts,
        "algos": cfg.algos,
    }
