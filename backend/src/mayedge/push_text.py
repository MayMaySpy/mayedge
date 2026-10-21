"""The words of every push. Pure functions; docs/push-rules.md is the source."""

from __future__ import annotations

import calendar
import time
from typing import Any

_FAMILIES = {
    "planner": "Planner",
    "trail": "Trail",
    "chase": "Chase",
    "grid": "Grid",
    "ladder": "Ladder",
    "twap": "TWAP",
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
    head = f"Yesterday: Portfolio {_signed_usd(total)}" + (
        f" ({', '.join(moved)})" if moved else ""
    )
    return f"{head} · {journal.removeprefix('Yesterday: ')}"


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
