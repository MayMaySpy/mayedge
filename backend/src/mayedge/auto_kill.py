"""Auto kill when live uPnL crosses configured USD loss floor or profit target."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mayedge.config import settings
from mayedge.kill import KillResult
from mayedge.lighter.models import Position, to_float

logger = logging.getLogger(__name__)

RunKillFn = Callable[..., Any]


def auto_kill_path() -> Path:
    return Path(settings.db_path).resolve().parent / "auto_kill.json"


@dataclass
class AutoKillConfig:
    armed: bool = False
    loss_usd: float | None = None
    profit_usd: float | None = None


@dataclass
class AutoKillState:
    config: AutoKillConfig = field(default_factory=AutoKillConfig)
    fired_at: int | None = None
    fired_reason: str | None = None
    fired_upnl: float | None = None
    last_kill_status: str | None = None


def _position_upnl(pos: Position | dict[str, Any]) -> float:
    if isinstance(pos, dict):
        size = to_float(pos.get("size", "0"))
        entry = to_float(pos.get("entry_price", "0"))
        mark = to_float(pos.get("mark_price", "0"))
        fallback = to_float(pos.get("unrealized_pnl", "0"))
    else:
        size = to_float(pos.size)
        entry = to_float(pos.entry_price)
        mark = to_float(pos.mark_price)
        fallback = to_float(pos.unrealized_pnl)
    if mark > 0 and entry > 0 and size != 0:
        return (mark - entry) * size
    return fallback


def live_upnl(positions: list[Position] | list[dict[str, Any]]) -> float:
    return sum(_position_upnl(p) for p in positions)


def breach(upnl: float, cfg: AutoKillConfig) -> str | None:
    if cfg.loss_usd is not None and upnl <= -cfg.loss_usd:
        return "loss"
    if cfg.profit_usd is not None and upnl >= cfg.profit_usd:
        return "profit"
    return None


def _validate_thresholds(loss_usd: float | None, profit_usd: float | None) -> None:
    if loss_usd is None and profit_usd is None:
        raise ValueError("set at least one of loss_usd or profit_usd")
    if loss_usd is not None and loss_usd <= 0:
        raise ValueError("loss_usd must be positive")
    if profit_usd is not None and profit_usd <= 0:
        raise ValueError("profit_usd must be positive")


def _config_from_dict(data: dict[str, Any]) -> AutoKillConfig:
    loss = data.get("loss_usd")
    profit = data.get("profit_usd")
    return AutoKillConfig(
        armed=bool(data.get("armed", False)),
        loss_usd=float(loss) if loss is not None else None,
        profit_usd=float(profit) if profit is not None else None,
    )


def load_auto_kill(path: Path | None = None) -> AutoKillState:
    p = path or auto_kill_path()
    if not p.is_file():
        return AutoKillState()
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            raise ValueError("root must be a mapping")
        cfg = _config_from_dict(data.get("config") or data)
        fired_at = data.get("fired_at")
        return AutoKillState(
            config=cfg,
            fired_at=int(fired_at) if fired_at is not None else None,
            fired_reason=data.get("fired_reason"),
            fired_upnl=float(data["fired_upnl"]) if data.get("fired_upnl") is not None else None,
            last_kill_status=data.get("last_kill_status"),
        )
    except Exception:
        logger.exception("failed to parse %s; using defaults", p)
        return AutoKillState()


def save_auto_kill(state: AutoKillState, path: Path | None = None) -> None:
    p = path or auto_kill_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = state.config
    payload: dict[str, Any] = {
        "config": {
            "armed": cfg.armed,
            "loss_usd": cfg.loss_usd,
            "profit_usd": cfg.profit_usd,
        },
        "fired_at": state.fired_at,
        "fired_reason": state.fired_reason,
        "fired_upnl": state.fired_upnl,
        "last_kill_status": state.last_kill_status,
    }
    p.write_text(json.dumps(payload, indent=2) + "\n")


class AutoKill:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._state = load_auto_kill(path)
        self._run_kill: RunKillFn | None = None
        self._emit: Callable[[dict[str, Any]], None] | None = None
        self._firing = False
        self._live_upnl_fn: Callable[[list[Any]], float] = live_upnl

    def set_live_upnl_fn(self, fn: Callable[[list[Any]], float]) -> None:
        self._live_upnl_fn = fn

    def start(
        self,
        *,
        run_kill: RunKillFn,
        emit: Callable[[dict[str, Any]], None],
    ) -> None:
        self._run_kill = run_kill
        self._emit = emit
        self._broadcast()

    def stop(self) -> None:
        self._run_kill = None
        self._emit = None

    def view(self) -> dict[str, Any]:
        cfg = self._state.config
        return {
            "type": "auto_kill",
            "armed": cfg.armed,
            "loss_usd": cfg.loss_usd,
            "profit_usd": cfg.profit_usd,
            "fired_at": self._state.fired_at,
            "fired_reason": self._state.fired_reason,
            "fired_upnl": self._state.fired_upnl,
            "last_kill_status": self._state.last_kill_status,
        }

    def _broadcast(self) -> None:
        if self._emit:
            self._emit(self.view())

    def configure(
        self,
        *,
        armed: bool,
        loss_usd: float | None,
        profit_usd: float | None,
        current_positions: list[Any] | None = None,
    ) -> dict[str, Any]:
        if armed:
            _validate_thresholds(loss_usd, profit_usd)
            if current_positions is not None:
                upnl = self._live_upnl_fn(current_positions)
                cfg_probe = AutoKillConfig(armed=True, loss_usd=loss_usd, profit_usd=profit_usd)
                if breach(upnl, cfg_probe):
                    raise ValueError(
                        f"current uPnL {upnl:.2f} already past threshold; disarm or adjust limits"
                    )
        self._state.config = AutoKillConfig(
            armed=armed,
            loss_usd=loss_usd,
            profit_usd=profit_usd,
        )
        save_auto_kill(self._state, self._path)
        self._broadcast()
        return self.view()

    def on_gateway(self, msg: dict[str, Any]) -> None:
        if msg.get("type") != "account":
            return
        if self._firing or not self._state.config.armed:
            return
        positions = msg.get("positions") or []
        if not positions:
            return
        upnl = self._live_upnl_fn(positions)
        reason = breach(upnl, self._state.config)
        if reason is None:
            return
        self._firing = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._firing = False
            return
        loop.create_task(self._fire(reason=reason, upnl=upnl))

    async def _fire(self, *, reason: str, upnl: float) -> None:
        self._state.config.armed = False
        save_auto_kill(self._state, self._path)
        self._broadcast()
        kill_status = "error"
        try:
            if self._run_kill is None:
                raise RuntimeError("auto_kill not started")
            result: KillResult = await self._run_kill(flatten=True)
            kill_status = result.status
        except Exception:
            logger.exception("auto_kill run_kill failed")
        self._state.fired_at = int(time.time() * 1000)
        self._state.fired_reason = reason
        self._state.fired_upnl = upnl
        self._state.last_kill_status = kill_status
        save_auto_kill(self._state, self._path)
        self._broadcast()
        self._firing = False


auto_kill = AutoKill()
