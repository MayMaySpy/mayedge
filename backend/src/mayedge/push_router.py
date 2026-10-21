"""Turn desk messages into pushes: which fact goes out, and when."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mayedge.auto_kill import FLATTEN_SLIPPAGE_STEPS
from mayedge.push_settings import Clock, PushSettings
from mayedge.push_text import (
    _FAMILIES,
    _alert_text,
    _at_minutes,
    _count,
    _kill_fired_text,
    _minutes,
    _num,
    _px,
    _role_qty_price,
    _seconds_until_hhmm,
    _side_word,
    _signed,
    _span,
    _target_r,
    _trim,
    _usd,
    _utc_date,
    daily_text,
    freeze_text,
    status_text,
)

logger = logging.getLogger(__name__)


_LIVE_STATUS = frozenset({"running", "paused"})


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
        self._position_pnl: list[float | None] = []
        self._kill_armed = False
        self._kill_floor: float | None = None
        self._kill_target: float | None = None
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
        self._kill_armed = bool(msg.get("armed"))
        self._kill_floor = _opt_num(msg.get("loss_usd"))
        self._kill_target = _opt_num(msg.get("profit_usd"))
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
        pnls: list[float | None] = []
        for pos in msg.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            size = _num(pos.get("size"))
            if size == 0:
                continue
            open_rows.append({"symbol": str(pos.get("symbol") or "?"), "size": _signed(size)})
            pnls.append(_opt_num(pos.get("unrealized_pnl")))
        self._positions = open_rows
        self._position_pnl = pnls
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

    def status_text(self, network: str) -> str:
        """The answer to /status, from the latest desk messages."""
        return status_text(
            network=network,
            now_s=self._clock.now(),
            positions=[
                (p["symbol"], p["size"], pnl)
                for p, pnl in zip(self._positions, self._position_pnl, strict=True)
            ],
            upnl=self._upnl,
            account_live=self._account_live,
            live_algos=self._live_algos,
            kill_armed=self._kill_armed,
            kill_floor=self._kill_floor,
            kill_target=self._kill_target,
            venue_since=self._venue_since,
            venue_reason=self._venue_reason,
        )

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


def _opt_num(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
