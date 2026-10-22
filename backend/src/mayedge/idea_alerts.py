"""Price alerts on an Idea. A fact, never an order. Rules: docs/idea-rules.md A1–A11. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from mayedge.ideas import Refusal
from mayedge.numbers import fmt_decimal, parse_decimal

KINDS = ("level", "move", "day")
LEVEL_WAYS = ("above", "below")
MOVE_WAYS = ("up", "down", "either")
MAX_PER_IDEA = 20
NOTE_MAX = 120
CHECK_S = 2.0
REPEAT_AFTER_MS = 15 * 60 * 1000
# L3: a single entry price counts as In zone within 0.25% of it.
_BAND = Decimal("0.0025")
_SEP = " · "
_MINUS = "−"
_BELL = "\U0001f514 "


@dataclass(frozen=True, slots=True)
class AlertSpec:
    """A body that passed A2–A4 and A11 on its own. Arming needs Last too."""

    kind: str
    direction: str | None
    price: str | None
    pct: str | None
    repeat: bool
    note: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class Armed:
    direction: str
    base: str | None


@dataclass(frozen=True, slots=True)
class Alert:
    id: int
    idea_id: str
    symbol: str
    kind: str
    direction: str
    price: str | None
    pct: str | None
    base: str | None
    repeat: bool
    label: str
    note: str
    status: str
    fires: int
    armed_at: int
    fired_at: int | None


def spec_of(body: dict[str, Any]) -> AlertSpec | Refusal:
    try:
        return _spec(body)
    except Refusal as refused:
        return refused


def arm(spec: AlertSpec, last: Decimal | None, change: Decimal | None) -> Armed:
    """A2, A3, A4: the direction and base an alert holds from now. Raises Refusal."""
    if spec.kind == "level":
        price = _dec(spec.price or "")
        if spec.direction is not None:
            return Armed(spec.direction, None)
        if last is None:
            raise Refusal("direction", "No Last for this Market yet. Pick above or below.")
        if price == last:
            raise Refusal("price", "Last is already there.")
        return Armed("above" if price > last else "below", None)
    way = spec.direction or "either"
    if spec.kind == "move":
        if last is None:
            raise Refusal(
                "pct", "No Last for this Market yet, so a move has nothing to start from."
            )
        return Armed(way, fmt_decimal(last))
    if change is not None and _day_met(way, _dec(spec.pct or ""), change):
        raise Refusal("pct", f"Daily Change is already {_signed_pct(change)}.")
    return Armed(way, None)


def known(alert: Alert, last: Decimal | None, change: Decimal | None) -> bool:
    """A5: what the alert reads is known."""
    return change is not None if alert.kind == "day" else last is not None


def met(alert: Alert, last: Decimal | None, change: Decimal | None) -> bool:
    """A2–A5. Unknown is never met."""
    if not known(alert, last, change):
        return False
    if alert.kind == "level":
        assert last is not None
        price = _dec(alert.price or "")
        return last >= price if alert.direction == "above" else last <= price
    if alert.kind == "move":
        assert last is not None
        moved = _moved(alert, last)
        if moved is None:
            return False
        pct = _dec(alert.pct or "")
        return _way_met(alert.direction, moved, pct)
    assert change is not None
    return _day_met(alert.direction, _dec(alert.pct or ""), change)


def rearm_due(
    alert: Alert, now_ms: int, last: Decimal | None, change: Decimal | None
) -> Armed | None:
    """A8 for Repeat: 15 minutes after the fire, armed again from Last now. None waits."""
    if not alert.repeat or alert.status != "fired" or alert.fired_at is None:
        return None
    if now_ms - alert.fired_at < REPEAT_AFTER_MS:
        return None
    return rearm_now(alert, last, change)


def rearm_now(alert: Alert, last: Decimal | None, change: Decimal | None) -> Armed | None:
    """A8: arm again as if new. A Level picks its direction afresh; None while it cannot."""
    if alert.kind == "level":
        if last is None:
            return None
        price = _dec(alert.price or "")
        if price == last:
            return None
        return Armed("above" if price > last else "below", None)
    if alert.kind == "move":
        return None if last is None else Armed(alert.direction, fmt_decimal(last))
    if change is None or _day_met(alert.direction, _dec(alert.pct or ""), change):
        return None
    return Armed(alert.direction, None)


def alert_text(
    alert: Alert,
    last: Decimal | None,
    change: Decimal | None,
    *,
    at_start: bool = False,
) -> str:
    """The fired line, without the bell (the log line). ``push_text`` adds the bell and note."""
    sym = alert.symbol
    last_bit = f"Last {px(fmt_decimal(last) or '')}" if last is not None else "Last unknown"
    if alert.kind == "level":
        bits = [f"{sym} {alert.direction} {px(alert.price or '')}"]
        if alert.label:
            bits.append(alert.label)
    elif alert.kind == "move":
        moved = _moved(alert, last) if last is not None else None
        head = f"{sym} moved {_signed_pct(moved) if moved is not None else '?'}"
        bits = [f"{head} from {px(alert.base or '')} (alert {_way_pct(alert)})"]
    else:
        shown = _signed_pct(change) if change is not None else "?"
        bits = [f"{sym} Daily Change {shown} (alert {_way_pct(alert)})"]
    bits.append(last_bit)
    if at_start:
        bits.append("met when the desk started")
    return _SEP.join(bits)


def push_text(log_line: str, note: str) -> str:
    """A11: the bell, the line, and the note under it."""
    text = _BELL + log_line
    return f"{text}\n{note}" if note else text


def plan_levels(
    low: str | None,
    high: str | None,
    stop: str | None,
    targets: list[str],
    last: Decimal | None,
    watched: set[Decimal],
) -> list[tuple[str, str]]:
    """A10: (price, label) for each Plan price Last is not on. Skips armed Level prices."""
    if last is None:
        return []
    out: list[tuple[str, str]] = []
    taken = set(watched)

    def add(price: str | None, label: str) -> None:
        if price is None:
            return
        value = _dec(price)
        if value == last or value in taken:
            return
        taken.add(value)
        out.append((price, label))

    if low is not None and high is not None and not _in_zone(_dec(low), _dec(high), last):
        add(low if last < _dec(low) else high, "Entry zone")
    add(stop, "Stop")
    for index, target in enumerate(targets, start=1):
        add(target, f"T{index}")
    return out


def px(text: str) -> str:
    """A stored price with thousands separators, its digits kept."""
    if not text:
        return text
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    whole, dot, frac = text.partition(".")
    try:
        grouped = f"{int(whole):,}" if whole else "0"
    except ValueError:
        return sign + text
    return f"{sign}{grouped}{dot}{frac}"


def decimal_of(raw: object) -> Decimal | None:
    """A float from the gateway as a Decimal; None when it is missing or not finite."""
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        dec = Decimal(str(raw))
    except InvalidOperation:
        return None
    return dec if dec.is_finite() else None


def _spec(body: dict[str, Any]) -> AlertSpec:
    kind = body.get("kind")
    if kind not in KINDS:
        raise Refusal("kind", "An alert is a level, a move or a day.")
    direction = body.get("direction")
    if direction in (None, ""):
        direction = None
    elif kind == "level" and direction not in LEVEL_WAYS:
        raise Refusal("direction", "A level is above or below.")
    elif kind != "level" and direction not in MOVE_WAYS:
        raise Refusal("direction", "A move is up, down or either.")
    note = body.get("note") or ""
    if not isinstance(note, str):
        raise Refusal("note", "Type words.")
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise Refusal("note", f"A note is at most {NOTE_MAX} characters.")
    if kind == "level":
        price = _price_in(body.get("price"))
        return AlertSpec("level", direction, price, None, bool(body.get("repeat")), note)
    pct = _pct_in(body.get("pct"))
    return AlertSpec(kind, direction, None, pct, bool(body.get("repeat")), note)


def _price_in(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise Refusal("price", "Type the price.")
    text = raw.strip()
    try:
        value = parse_decimal(text)
    except ValueError:
        raise Refusal("price", "Type the price.") from None
    if value <= 0:
        raise Refusal("price", "A price is above 0.")
    return text


def _pct_in(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise Refusal("pct", "Type the percent.")
    text = raw.strip().rstrip("%").strip()
    try:
        value = parse_decimal(text)
    except ValueError:
        raise Refusal("pct", "Type the percent.") from None
    if value <= 0 or value > 100:
        raise Refusal("pct", "A percent is above 0 and at most 100.")
    return text


def _dec(text: str) -> Decimal:
    return parse_decimal(text)


def _moved(alert: Alert, last: Decimal) -> Decimal | None:
    if not alert.base:
        return None
    base = _dec(alert.base)
    if base <= 0:
        return None
    return (last - base) / base * 100


def _way_met(way: str, value: Decimal, pct: Decimal) -> bool:
    if way == "up":
        return value >= pct
    if way == "down":
        return value <= -pct
    return abs(value) >= pct


def _day_met(way: str, pct: Decimal, change: Decimal) -> bool:
    return _way_met(way, change, pct)


def _in_zone(low: Decimal, high: Decimal, last: Decimal) -> bool:
    if low == high:
        return abs(last - low) / low <= _BAND
    return low <= last <= high


def _signed_pct(value: Decimal) -> str:
    shown = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = fmt_decimal(abs(shown))
    if shown > 0:
        return f"+{text}%"
    if shown < 0:
        return f"{_MINUS}{text}%"
    return f"{text}%"


def _way_pct(alert: Alert) -> str:
    mark = {"up": "+", "down": _MINUS}.get(alert.direction, "±")
    return f"{mark}{alert.pct}%"
