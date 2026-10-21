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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import yaml

from mayedge.alerts import resolve_alerts_config_path
from mayedge.auto_kill import FLATTEN_SLIPPAGE_STEPS
from mayedge.config import settings

logger = logging.getLogger(__name__)

# httpx logs the request URL at INFO, and that URL contains the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_MAX_CHARS = 4000
_PACE_S = 1.0
_FAIL_WAITS = (2.0, 4.0, 8.0)
_MAX_ATTEMPTS = 3
_MAX_429 = 8
_FAMILIES = {
    "planner": "Planner",
    "trail": "Trail",
    "chase": "Chase",
    "grid": "Grid",
    "ladder": "Ladder",
    "twap": "TWAP",
}
_LIVE_STATUS = frozenset({"running", "paused"})


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


def boot_text(
    network: str,
    algos: int,
    positions: int,
    down: dict[str, Any] | None = None,
) -> str:
    plain = (
        f"Desk up ({network}) — {_count(algos, 'algo', 'algos')} restored, "
        f"{_count(positions, 'Position', 'Positions')} open"
    )
    if not down:
        return plain
    how = "clean stop" if down.get("clean") else "not a clean stop"
    return (
        f"Desk up ({network}) after {_hm(int(down['to']) - int(down['from']))} down "
        f"({_hm_clock(int(down['from']))}–{_hm_clock(int(down['to']))} UTC, {how}). "
        "Trails, Planner trailing parts and Auto kill were not watching; venue stops held. "
        f"{_count(algos, 'algo', 'algos')} restored, "
        f"{_count(positions, 'Position', 'Positions')} open."
    )


def freeze_text(
    start_ms: int,
    end_ms: int,
    *,
    positions: int,
    upnl: float | None,
    account_live: bool,
) -> str:
    if account_live:
        tail = (
            f"{_count(positions, 'Position', 'Positions')} open, "
            f"uPnL {_signed_usd(0.0 if upnl is None else upnl)}"
        )
    else:
        tail = "Positions unknown until the account feed is back"
    return (
        f"Desk was frozen {_hm(end_ms - start_ms)} "
        f"({_hm_clock(start_ms)}–{_hm_clock(end_ms)} UTC). "
        "Trails, Planner trailing parts and Auto kill were not watching; venue stops held. "
        f"{tail}."
    )


class PushSink(Protocol):
    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None: ...


@dataclass
class _SeenAlgo:
    status: str
    fills: dict[str, int]


class PushRouter:
    """Turn desk messages into pushes. The first algo snapshot only seeds the diff."""

    def __init__(
        self,
        out: PushSink,
        cfg: PushSettings,
        clock: Clock,
        journal: Callable[[str], tuple[int, float, float, float]] | None = None,
        portfolio: Callable[[str], dict[str, float] | None] | None = None,
    ) -> None:
        self._out = out
        self._cfg = cfg
        self._clock = clock
        self._journal = journal
        self._portfolio = portfolio
        self._daily_sent_on: str | None = None
        self._algo_seeded = False
        self._algos: dict[str, _SeenAlgo] = {}
        self._live_algos = 0
        self._positions: list[dict[str, str]] = []
        self._upnl: float | None = None
        self._account_live = False
        self._kill_seeded = False
        self._kill_fired_at: Any = None
        self._kill_status: str | None = None
        self._kill_announced = False
        self._venue_since: float | None = None
        self._venue_reason = ""
        self._venue_announced = False
        self._account_down_since: float | None = None
        self._account_announced = False

    def on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "alerts":
            self._on_alerts(msg)
        elif kind == "algo":
            self._on_algo(msg)
        elif kind == "auto_kill":
            self._on_kill(msg)
        elif kind == "account":
            self._on_account(msg)
        elif kind == "feed_health":
            self._on_feed(msg)
        elif kind == "desk_freeze":
            self._on_freeze(msg)
        self.poll()

    def poll(self) -> None:
        self._poll_venue()
        self._poll_account()
        self._maybe_kill_result()
        self._poll_daily()

    def _on_alerts(self, msg: dict[str, Any]) -> None:
        if self._cfg.alerts == "off":
            return
        for event in msg.get("events") or []:
            if not isinstance(event, dict):
                continue
            text, urgent = _alert_text(event, self._cfg.alerts)
            if text is None:
                continue
            event_id = event.get("id") or event.get("ts")
            self._out.push(f"alert:{event_id}", text, urgent=urgent)

    def _on_algo(self, msg: dict[str, Any]) -> None:
        rows = _algo_rows(msg)
        self._live_algos = sum(1 for row in rows.values() if row.get("status") in _LIVE_STATUS)
        if not self._algo_seeded:
            self._algo_seeded = True
            for algo_id, row in rows.items():
                self._algos[algo_id] = _seen(row)
            return
        for algo_id, row in rows.items():
            prev = self._algos.get(algo_id)
            self._emit_algo(algo_id, row, prev)
            self._algos[algo_id] = _seen(row)

    def _emit_algo(self, algo_id: str, row: dict[str, Any], prev: _SeenAlgo | None) -> None:
        status = str(row.get("status") or "")
        family = _FAMILIES.get(str(row.get("algo_type") or ""), "Algo")
        symbol = str(row.get("symbol") or "")
        if status == "error" and (prev is None or prev.status != "error"):
            error = row.get("error") or "unknown"
            self._out.push(
                f"algo:{algo_id}:error",
                f"{family} {symbol} stopped with an error: {error}",
            )
            return
        if self._cfg.algos != "lifecycle" or family not in {"Planner", "Trail"}:
            return
        if family == "Planner":
            self._emit_planner(algo_id, row, prev)
        else:
            self._emit_trail(algo_id, row, prev)
        if status == "done" and (prev is None or prev.status != "done"):
            side = _side_word(row.get("side"))
            label = f"{symbol} {side}".strip()
            self._out.push(f"algo:{algo_id}:done", f"{family} {label}: done")

    def _emit_planner(self, algo_id: str, row: dict[str, Any], prev: _SeenAlgo | None) -> None:
        fills = _role_fills(row)
        before = prev.fills if prev else {}
        symbol = str(row.get("symbol") or "")
        side = _side_word(row.get("side"))
        plan = (row.get("planner") or {}).get("plan") or {}
        if fills.get("entry", 0) > before.get("entry", 0):
            qty, px = _role_qty_price(row, "entry")
            stop = _px(_num(plan.get("stop")))
            risk = _usd(abs(_num(plan.get("risk_usd"))))
            self._out.push(
                f"algo:{algo_id}:entry",
                f"Planner {symbol} {side}: entry filled {qty} @ {px} · stop {stop} · risk {risk}",
            )
        if fills.get("stop", 0) > before.get("stop", 0):
            _qty, px = _role_qty_price(row, "stop")
            self._out.push(f"algo:{algo_id}:stop", f"Planner {symbol}: stop filled @ {px}")
        for role, count in sorted(fills.items()):
            if not role.startswith("tp") or count <= before.get(role, 0):
                continue
            index = role.removeprefix("tp") or "1"
            _qty, px = _role_qty_price(row, role)
            r_text = _target_r(plan, index)
            self._out.push(
                f"algo:{algo_id}:target-{index}",
                f"Planner {symbol}: target {index} filled @ {px} ({r_text})",
            )

    def _emit_trail(self, algo_id: str, row: dict[str, Any], prev: _SeenAlgo | None) -> None:
        kind = str((row.get("trail") or {}).get("kind") or "")
        filled = _num(row.get("filled"))
        before = (prev.fills.get("filled", 0) / 1_000_000) if prev else 0.0
        if filled <= before or kind not in {"entry", "stop", "tp"}:
            return
        symbol = str(row.get("symbol") or "")
        fills = [f for f in (row.get("fills") or []) if isinstance(f, dict)]
        px = _px(_num(fills[-1].get("price")) if fills else _num(row.get("rest_price")))
        if kind == "entry":
            side = _side_word(row.get("side"))
            qty = _trim(filled)
            self._out.push(
                f"algo:{algo_id}:entry",
                f"Trail {symbol} {side}: entry filled {qty} @ {px}",
            )
        elif kind == "stop":
            self._out.push(f"algo:{algo_id}:stop", f"Trail {symbol}: stop filled @ {px}")
        else:
            self._out.push(f"algo:{algo_id}:target", f"Trail {symbol}: target filled @ {px}")

    def _on_kill(self, msg: dict[str, Any]) -> None:
        fired_at = msg.get("fired_at")
        status = msg.get("last_kill_status")
        status_s = str(status) if status else None
        if not self._kill_seeded:
            self._kill_seeded = True
            self._kill_fired_at = fired_at
            self._kill_status = status_s
            return
        if fired_at and fired_at != self._kill_fired_at:
            self._kill_fired_at = fired_at
            self._kill_announced = False
            self._kill_status = None
            self._out.push(
                f"autokill:{fired_at}",
                _kill_fired_text(msg),
                urgent=True,
            )
        if status_s and status_s != self._kill_status:
            self._kill_status = status_s

    def _maybe_kill_result(self) -> None:
        if self._kill_announced or not self._kill_status:
            return
        if self._kill_status == "partial":
            self._announce_kill(False)
        elif self._kill_status == "killed" and not self._positions:
            self._announce_kill(True)

    def _announce_kill(self, flat: bool) -> None:
        self._kill_announced = True
        tries = len(FLATTEN_SLIPPAGE_STEPS)
        if flat:
            text = "Auto kill: flattened, 0 Positions open"
        else:
            noun = "Position" if len(self._positions) == 1 else "Positions"
            listed = ", ".join(f"{p['symbol']} {p['size']}" for p in self._positions) or "unknown"
            text = (
                f"⚠️ Auto kill could not flatten after {tries} tries — "
                f"{len(self._positions)} {noun} open: {listed}"
            )
        self._out.push(f"autokill:{self._kill_fired_at}:result", text, urgent=True)

    def _on_account(self, msg: dict[str, Any]) -> None:
        open_rows: list[dict[str, str]] = []
        for pos in msg.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            size = _num(pos.get("size"))
            if size == 0:
                continue
            open_rows.append({"symbol": str(pos.get("symbol") or "?"), "size": _signed(size)})
        self._positions = open_rows
        raw = msg.get("unrealized_pnl")
        self._upnl = _num(raw) if raw not in (None, "") else None

    def _on_freeze(self, msg: dict[str, Any]) -> None:
        try:
            start = int(msg["from"])
            end = int(msg["to"])
        except (KeyError, TypeError, ValueError):
            return
        text = msg.get("text")
        if not isinstance(text, str) or not text:
            text = freeze_text(
                start,
                end,
                positions=len(self._positions),
                upnl=self._upnl,
                account_live=self._account_live,
            )
        self._out.push(f"freeze:{end}", text, urgent=True)

    def _on_feed(self, msg: dict[str, Any]) -> None:
        since = msg.get("venue_down_since") or 0
        try:
            since_s = float(since) / 1000.0
        except (TypeError, ValueError):
            since_s = 0.0
        if since_s > 0:
            if self._venue_since is None:
                self._venue_since = since_s
            self._venue_reason = str(msg.get("venue_down_reason") or "")
        elif self._venue_announced:
            lasted = self._clock.now() - (self._venue_since or self._clock.now())
            self._out.push("venue", f"Lighter back after {_span(lasted)}", force=True)
            self._venue_announced = False
            self._venue_since = None
            self._venue_reason = ""
        else:
            self._venue_since = None
        account = str(msg.get("account_ws") or "")
        self._account_live = account == "live"
        if account == "live":
            self._account_down_since = None
            self._account_announced = False
        elif self._account_down_since is None:
            self._account_down_since = self._clock.now()

    def _poll_venue(self) -> None:
        if self._venue_since is None or self._venue_announced:
            return
        if self._clock.now() - self._venue_since < self._cfg.venue_down_after_s:
            return
        when = time.strftime("%H:%M", time.gmtime(self._venue_since))
        reason = f" ({self._venue_reason})" if self._venue_reason else ""
        self._out.push("venue", f"Lighter down since {when} UTC{reason}")
        self._venue_announced = True

    def _poll_account(self) -> None:
        if self._account_announced or self._account_down_since is None:
            return
        elapsed = self._clock.now() - self._account_down_since
        if elapsed < self._cfg.account_stale_after_s:
            return
        if not self._positions and self._live_algos <= 0:
            return
        bits: list[str] = []
        if self._live_algos:
            bits.append(_count(self._live_algos, "algo", "algos") + " live")
        if self._positions:
            bits.append(_count(len(self._positions), "Position", "Positions") + " open")
        self._out.push(
            "account_stale",
            f"⚠️ Account feed stale {_span(elapsed)} with {' and '.join(bits)} — desk is blind",
            urgent=True,
        )
        self._account_announced = True

    def _poll_daily(self) -> None:
        if self._daily_wait() != 0.0:
            return
        today = _utc_date(time.gmtime(self._clock.now()))
        self._daily_sent_on = today
        if self._journal is None:
            return
        day = time.strftime("%Y-%m-%d", time.gmtime(self._clock.now() - 86_400))
        try:
            count, net, fees, funding = self._journal(day)
        except Exception:
            logger.warning("daily journal push skipped")
            return
        portfolio: dict[str, float] | None = None
        if self._portfolio is not None:
            try:
                portfolio = self._portfolio(day)
            except Exception:
                # D1: the journal part still goes out.
                logger.warning("daily portfolio part skipped")
        self._out.push(f"journal:{today}", daily_text(count, net, fees, funding, portfolio))

    def _daily_wait(self) -> float | None:
        at = self._cfg.daily_at
        if not at:
            return None
        now = self._clock.now()
        stamp = time.gmtime(now)
        if self._daily_sent_on == _utc_date(stamp):
            return _seconds_until_hhmm(now + 60, at)
        if _minutes(stamp) >= _at_minutes(at):
            return 0.0
        return _seconds_until_hhmm(now, at)

    def due_in(self) -> float | None:
        """Seconds until a debounced push is due. None when nothing is waiting."""
        waits: list[float] = []
        now = self._clock.now()
        if self._venue_since is not None and not self._venue_announced:
            waits.append(self._venue_since + self._cfg.venue_down_after_s - now)
        exposed = bool(self._positions) or self._live_algos > 0
        if self._account_down_since is not None and not self._account_announced and exposed:
            waits.append(self._account_down_since + self._cfg.account_stale_after_s - now)
        daily = self._daily_wait()
        if daily is not None:
            waits.append(daily)
        if not waits:
            return None
        return max(0.0, min(waits))


def _alert_text(event: dict[str, Any], mode: str) -> tuple[str | None, bool]:
    facts = [f for f in (event.get("facts") or []) if isinstance(f, dict)]
    near = next((f for f in facts if f.get("kind") == "near_liq"), None)
    held = str(event.get("held") or "")
    rule = str(event.get("rule") or "")
    severity = int(event.get("severity") or 0)
    if near is not None or rule == "near_liq":
        if mode == "off":
            return None, False
        if mode == "urgent" and severity < 3 and near is None:
            return None, False
        return _near_text(event, near), True
    if mode == "held" and not held:
        return None, False
    if mode == "urgent" and severity < 3:
        return None, False
    symbol = str(event.get("symbol") or "")
    note = str(event.get("note") or "")
    if held:
        move = next((f for f in facts if f.get("kind") == "move" and f.get("multiple")), None)
        if move is not None:
            return (
                f"{symbol} spike: price {float(move['multiple']):.1f}× the hour's biggest minute, "
                f"{float(move.get('value') or 0):+.1f}% · held",
                False,
            )
        return f"{symbol}: {note} · held", False
    text = note or f"{symbol} {rule}".strip()
    return (text or None), False


def _near_text(event: dict[str, Any], fact: dict[str, Any] | None) -> str:
    symbol = str(event.get("symbol") or "")
    mark = _px(_num(event.get("price")))
    liq = _px(_num((fact or {}).get("liquidation_price")))
    distance = _num((fact or {}).get("value"))
    return f"🔴 {symbol} near liquidation — mark {mark}, liq {liq} ({distance:.1f}%)"


def _kill_fired_text(msg: dict[str, Any]) -> str:
    upnl = _signed_usd(_num(msg.get("fired_upnl")))
    if msg.get("fired_reason") == "profit":
        target = _signed_usd(abs(_num(msg.get("profit_usd"))))
        crossed = f"the {target} target"
    else:
        floor = _signed_usd(-abs(_num(msg.get("loss_usd"))))
        crossed = f"the {floor} floor"
    return (
        f"⛔ Auto kill fired: uPnL {upnl} crossed {crossed}. "
        "Stopping algos, cancelling, flattening."
    )


def _algo_rows(msg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for key in ("history", "working"):
        for row in msg.get(key) or []:
            if isinstance(row, dict) and row.get("algo_id"):
                by_id[str(row["algo_id"])] = row
    return by_id


def _seen(row: dict[str, Any]) -> _SeenAlgo:
    fills = _role_fills(row)
    if row.get("algo_type") == "trail":
        fills = {"filled": int(_num(row.get("filled")) * 1_000_000)}
    return _SeenAlgo(status=str(row.get("status") or ""), fills=fills)


def _role_fills(row: dict[str, Any]) -> dict[str, int]:
    roles = (row.get("planner") or {}).get("roles") or {}
    counts: dict[str, int] = {}
    for fill in row.get("fills") or []:
        if not isinstance(fill, dict):
            continue
        role = str(roles.get(str(fill.get("clip_seq"))) or "")
        if role:
            counts[role] = counts.get(role, 0) + 1
    return counts


def _role_qty_price(row: dict[str, Any], role: str) -> tuple[str, str]:
    roles = (row.get("planner") or {}).get("roles") or {}
    qty = 0.0
    notional = 0.0
    last = 0.0
    for fill in row.get("fills") or []:
        if not isinstance(fill, dict):
            continue
        if str(roles.get(str(fill.get("clip_seq"))) or "") != role:
            continue
        q = _num(fill.get("qty"))
        px = _num(fill.get("price"))
        qty += q
        notional += q * px
        last = px
    if role == "entry":
        qty = _num((row.get("planner") or {}).get("entry_filled")) or qty
    price = notional / qty if qty else last
    return _trim(qty), _px(price)


def _target_r(plan: dict[str, Any], index: str) -> str:
    for target in plan.get("targets") or []:
        if str(target.get("index")) == str(index):
            return f"{_num(target.get('r')):+.1f}R"
    return "+0.0R"


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
        if self._transport is None:
            token = settings.telegram_bot_token or ""
            chat = settings.telegram_chat_id or ""
            self._client = httpx.AsyncClient(timeout=10)
            self._transport = HttpxTransport(token, chat, self._client)
        self._stopped = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
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


def _f(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _num(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _px(value: float) -> str:
    text = f"{value:,.4f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _trim(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def daily_journal_text(count: int, net: float, fees: float, funding: float) -> str:
    """Yesterday's closed Round trips. Fees are a cost; funding keeps its sign."""
    if count <= 0:
        return "Yesterday: no Round trips."
    noun = "Round trip" if count == 1 else "Round trips"
    return (
        f"Yesterday: Net {_signed_usd(net)} over {count} {noun}, "
        f"fees {_usd(abs(fees))}, funding {_signed_usd(funding)}"
    )


_KIND_NAMES = {"perps": "Perps", "spot": "Spot", "llp": "LLP", "staking": "Staking"}


def daily_text(
    count: int, net: float, fees: float, funding: float, portfolio: dict[str, float] | None = None
) -> str:
    """D1: the Portfolio's day first, when the desk has it, then the journal's."""
    journal = daily_journal_text(count, net, fees, funding)
    if portfolio is None:
        return journal
    total = sum(portfolio.values())
    moved = [f"{_KIND_NAMES[k]} {_signed_usd(v)}" for k, v in portfolio.items() if round(v) != 0]
    head = f"Yesterday: Portfolio {_signed_usd(total)}" + (f" ({', '.join(moved)})" if moved else "")
    return f"{head} · {journal.removeprefix('Yesterday: ')}"


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


def _daily_at(raw: Any) -> str:
    text = str(raw or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return ""
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hour:02d}:{minute:02d}"


def _utc_date(stamp: time.struct_time) -> str:
    return f"{stamp.tm_year:04d}-{stamp.tm_mon:02d}-{stamp.tm_mday:02d}"


def _minutes(stamp: time.struct_time) -> int:
    return stamp.tm_hour * 60 + stamp.tm_min


def _at_minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _seconds_until_hhmm(now: float, hhmm: str) -> float:
    """Seconds until the next HH:MM UTC."""
    hour, minute = _at_minutes(hhmm) // 60, _at_minutes(hhmm) % 60
    stamp = time.gmtime(now)
    if stamp.tm_hour == hour and stamp.tm_min == minute:
        return 0.0
    target = calendar.timegm((stamp.tm_year, stamp.tm_mon, stamp.tm_mday, hour, minute, 0, 0, 0, 0))
    if target <= now:
        target += 86_400
    return max(0.0, target - now)


def _usd(value: float) -> str:
    return f"${abs(value):,.0f}"


def _signed_usd(value: float) -> str:
    """Whole dollars with a sign; an amount that rounds to $0 has none."""
    sign = "−" if value < 0 else "+"
    if round(abs(value)) == 0:
        sign = ""
    return f"{sign}{_usd(value)}"


def _signed(value: float) -> str:
    sign = "−" if value < 0 else "+"
    mag = abs(value)
    body = f"{mag:.1f}" if mag == int(mag) else _trim(mag)
    return sign + body


def _span(seconds: float) -> str:
    return f"{max(1, round(seconds / 60))}m"


def _hm(ms: int) -> str:
    total = max(0, int(ms) // 1000)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _hm_clock(ms: int) -> str:
    return time.strftime("%H:%M", time.gmtime(ms / 1000))


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _side_word(raw: Any) -> str:
    side = str(raw or "")
    if side == "buy":
        return "long"
    if side == "sell":
        return "short"
    return side
