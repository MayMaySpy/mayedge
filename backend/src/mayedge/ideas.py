"""An Idea is a note, not an order. Rules: docs/idea-rules.md. No I/O."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from mayedge.numbers import fmt_decimal, parse_decimal

SIDES = ("long", "short")
STATUSES = ("watching", "active", "closed", "dropped")
HORIZONS = ("scalp", "swing", "position")
OUTCOMES = ("worked", "failed", "missed", "wrong")
OPEN = ("watching", "active")
_MOVES = {
    ("watching", "active"),
    ("watching", "dropped"),
    ("active", "closed"),
    ("active", "dropped"),
    ("closed", "watching"),
    ("dropped", "watching"),
}
_LABEL = {
    "watching": "Watching",
    "active": "Active",
    "closed": "Closed",
    "dropped": "Dropped",
}
_DASH = "\u2013"
_ARROW = " \u2192 "
_SEP = " \u00b7 "


class Refusal(Exception):
    """A body that breaks a rule. ``field`` is the input that breaks it."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True, slots=True)
class Catalyst:
    text: str
    date: str | None


@dataclass(frozen=True, slots=True)
class Target:
    price: str
    pct: str | None


@dataclass(frozen=True, slots=True)
class Idea:
    symbol: str
    side: str
    thesis: str
    conviction: int
    horizon: str
    invalidation: str
    trigger: str
    tags: tuple[str, ...]
    catalysts: tuple[Catalyst, ...]
    entry_low: str | None
    entry_high: str | None
    stop: str | None
    targets: tuple[Target, ...]


@dataclass(frozen=True, slots=True)
class Clash:
    """An open Idea a new one would sit beside (I3)."""

    id: str
    symbol: str
    side: str


def normalise(body: dict[str, Any]) -> Idea | Refusal:
    """I2, I4, I5, P1, P2, P5. A Refusal names the field."""
    try:
        return _idea(body)
    except Refusal as refused:
        return refused


def second_open(open_ideas: list[Clash], symbol: str, side: str) -> Clash | None:
    """The open Idea on this Market and side, if the caller is making another (I3)."""
    want = symbol.strip().upper()
    for idea in open_ideas:
        if idea.symbol == want and idea.side == side:
            return idea
    return None


def plan_entry(idea: Idea) -> Decimal | None:
    if idea.entry_low is None or idea.entry_high is None:
        return None
    return (_dec(idea.entry_low) + _dec(idea.entry_high)) / 2


def r_of(idea: Idea) -> Decimal | None:
    entry = plan_entry(idea)
    if entry is None or idea.stop is None:
        return None
    risk = abs(entry - _dec(idea.stop))
    if risk == 0:
        return None
    return risk


def r_multiples(idea: Idea) -> list[Decimal] | None:
    """Each target's R, to 2 places (P3). None until the Plan is complete."""
    entry = plan_entry(idea)
    risk = r_of(idea)
    if entry is None or risk is None:
        return None
    step = Decimal("0.01")
    return [
        (abs(_dec(target.price) - entry) / risk).quantize(step, rounding=ROUND_HALF_UP)
        for target in idea.targets
    ]


def complete(idea: Idea) -> bool:
    """P6: a zone and a stop, and therefore an R."""
    return r_of(idea) is not None


def computed(idea: Idea) -> dict[str, Any]:
    """plan_entry, r and r_multiples as strings. Null when the Plan is not complete."""
    multiples = r_multiples(idea)
    return {
        "plan_entry": fmt_decimal(plan_entry(idea)),
        "r": fmt_decimal(r_of(idea)),
        "r_multiples": None if multiples is None else [format(item, "f") for item in multiples],
    }


def move(status_from: str, status_to: str) -> bool:
    """S2. The same status is not a move."""
    return (status_from, status_to) in _MOVES


def status_line(before: str, after: str) -> str:
    return f"{_LABEL[before]}{_ARROW}{_LABEL[after]}"


def planner_line(before: str, after: str, algo_id: str) -> str:
    named = f"Planner {algo_id}"
    if before == after:
        return named
    return f"{status_line(before, after)}{_SEP}{named}"


def plan_diff(before: Idea, after: Idea) -> str:
    """S4. Empty when nothing in the Plan moved."""
    parts = [
        _change("Entry", _zone(before), _zone(after)),
        _change("Stop", before.stop, after.stop),
        _change("Targets", _targets(before.targets), _targets(after.targets)),
        _change("Trigger", before.trigger or None, after.trigger or None),
    ]
    return _SEP.join(part for part in parts if part)


def outcome_of(raw: object) -> str | None:
    """S5. None is an unreviewed Idea. Anything else is refused."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw in OUTCOMES:
        return raw
    raise Refusal("outcome", "An outcome is Worked, Failed, Missed or Wrong.")


def log_text(raw: object) -> str:
    if not isinstance(raw, str):
        raise Refusal("body", "A log line is 1 to 2,000 characters.")
    text = raw.strip()
    if not text or len(text) > 2000:
        raise Refusal("body", "A log line is 1 to 2,000 characters.")
    return text


def algo_text(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise Refusal("algo_id", "Name the Planner.")
    return raw.strip()


def last_text(last: float | None, mark: float | None, mid: float | None) -> str | None:
    """L1. The first finite price above 0 wins. Zero is missing."""
    for raw in (last, mark, mid):
        text = _float_text(raw)
        if text is not None:
            return text
    return None


def blank_plan(idea: Idea) -> Idea:
    """The same Idea with no Plan, so a create can log the Plan it arrived with."""
    return replace(idea, entry_low=None, entry_high=None, stop=None, targets=(), trigger="")


def _idea(body: dict[str, Any]) -> Idea:
    symbol = str(body.get("symbol") or "").strip().upper()
    if not symbol:
        raise Refusal("symbol", "Name the Market.")
    side = body.get("side")
    if side not in SIDES:
        raise Refusal("side", "An Idea is long or short.")
    thesis = _words(body.get("thesis"), "thesis")
    if len(thesis) < 10:
        raise Refusal("thesis", "A Thesis needs at least 10 characters.")
    conviction = _conviction(body.get("conviction", 2))
    horizon = body.get("horizon", "swing")
    if horizon not in HORIZONS:
        raise Refusal("horizon", "Horizon is scalp, swing or position.")
    low = _price(body.get("entry_low"), "entry_low")
    high = _price(body.get("entry_high"), "entry_high")
    stop = _price(body.get("stop"), "stop")
    if (low is None) != (high is None):
        missing = "entry_high" if low else "entry_low"
        raise Refusal(missing, "A zone needs a low and a high.")
    if low is not None and high is not None and _dec(low) > _dec(high):
        raise Refusal("entry_high", "The entry runs from low to high.")
    targets = _targets_in(body.get("targets") or [], low)
    _sides(side, low, high, stop, targets)
    _shares(targets)
    return Idea(
        symbol=symbol,
        side=str(side),
        thesis=thesis,
        conviction=conviction,
        horizon=str(horizon),
        invalidation=_words(body.get("invalidation"), "invalidation"),
        trigger=_words(body.get("trigger"), "trigger"),
        tags=_tags(body.get("tags") or []),
        catalysts=_catalysts(body.get("catalysts") or []),
        entry_low=low,
        entry_high=high,
        stop=stop,
        targets=targets,
    )


def _conviction(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in (1, 2, 3):
        raise Refusal("conviction", "Conviction is 1, 2 or 3.")
    return raw


def _words(raw: object, field: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise Refusal(field, "Type words.")
    return raw.strip()


def _price(raw: object, field: str) -> str | None:
    """I6: keep the typed text. A JSON number is refused, not coerced."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise Refusal(field, "Type the price.")
    text = raw.strip()
    if not text:
        return None
    try:
        value = parse_decimal(text)
    except ValueError:
        raise Refusal(field, "Type the price.") from None
    if value <= 0:
        raise Refusal(field, "A price is above 0.")
    return text


def _targets_in(raw: object, low: str | None) -> tuple[Target, ...]:
    if not isinstance(raw, list):
        raise Refusal("targets", "Targets are a list.")
    if len(raw) > 4:
        raise Refusal("targets", "An Idea has at most 4 targets.")
    targets: list[Target] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise Refusal(f"targets.{index}", "A target needs a price.")
        price = _price(item.get("price"), f"targets.{index}")
        if price is None:
            raise Refusal(f"targets.{index}", "A target needs a price.")
        targets.append(Target(price, _pct(item.get("pct"), f"targets.{index}")))
    if targets and low is None:
        raise Refusal("entry_low", "Set the entry before a target.")
    return tuple(targets)


def _pct(raw: object, field: str) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise Refusal(field, "Type the size as text.")
    text = raw.strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        value = parse_decimal(text)
    except ValueError:
        raise Refusal(field, "A target size is a percent above 0 and at most 100.") from None
    if value <= 0 or value > 100:
        raise Refusal(field, "A target size is a percent above 0 and at most 100.")
    return text


def _sides(
    side: object,
    low: str | None,
    high: str | None,
    stop: str | None,
    targets: tuple[Target, ...],
) -> None:
    if low is None or high is None:
        return
    if stop is not None:
        if side == "long" and _dec(stop) >= _dec(low):
            raise Refusal("stop", "A long stop sits below the entry.")
        if side == "short" and _dec(stop) <= _dec(high):
            raise Refusal("stop", "A short stop sits above the entry.")
    for index, target in enumerate(targets):
        if side == "long" and _dec(target.price) <= _dec(high):
            raise Refusal(f"targets.{index}", "A long target sits above the entry.")
        if side == "short" and _dec(target.price) >= _dec(low):
            raise Refusal(f"targets.{index}", "A short target sits below the entry.")


def _shares(targets: tuple[Target, ...]) -> None:
    total = Decimal(0)
    for target in targets:
        if target.pct is not None:
            total += _dec(target.pct)
    if total > 100:
        raise Refusal("targets", "Target sizes add up to 100 or less.")


def _tags(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise Refusal("tags", "Tags are a list.")
    seen: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise Refusal("tags", "A tag is 1–24 characters.")
        tag = item.strip().lower()
        if not tag:
            continue
        if not 1 <= len(tag) <= 24:
            raise Refusal("tags", "A tag is 1–24 characters.")
        if tag not in seen:
            seen.append(tag)
    if len(seen) > 8:
        raise Refusal("tags", "An Idea has at most 8 tags.")
    return tuple(seen)


def _catalysts(raw: object) -> tuple[Catalyst, ...]:
    if not isinstance(raw, list):
        raise Refusal("catalysts", "Catalysts are a list.")
    if len(raw) > 12:
        raise Refusal("catalysts", "An Idea has at most 12 catalysts.")
    items: list[Catalyst] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise Refusal(f"catalysts.{index}", "A catalyst needs text.")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise Refusal(f"catalysts.{index}", "A catalyst needs text.")
        text = text.strip()
        if len(text) > 120:
            raise Refusal(f"catalysts.{index}", "A catalyst is at most 120 characters.")
        items.append(Catalyst(text, _day(item.get("date"), f"catalysts.{index}")))
    dated = [item for item in items if item.date is not None]
    undated = [item for item in items if item.date is None]
    dated.sort(key=lambda item: item.date or "")
    return tuple(dated + undated)


def _day(raw: object, field: str) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise Refusal(field, "A catalyst date is a UTC day, YYYY-MM-DD.")
    text = raw.strip()
    try:
        found = date.fromisoformat(text)
    except ValueError:
        raise Refusal(field, "A catalyst date is a UTC day, YYYY-MM-DD.") from None
    if found.isoformat() != text:
        raise Refusal(field, "A catalyst date is a UTC day, YYYY-MM-DD.")
    return text


def _dec(text: str) -> Decimal:
    return parse_decimal(text)


def _zone(idea: Idea) -> str | None:
    low, high = idea.entry_low, idea.entry_high
    if low is None and high is None:
        return None
    if low is None:
        return high
    if high is None or low == high:
        return low
    return f"{low}{_DASH}{high}"


def _targets(targets: tuple[Target, ...]) -> str | None:
    if not targets:
        return None
    bits: list[str] = []
    for index, target in enumerate(targets, start=1):
        bit = f"T{index} {target.price}"
        if target.pct:
            bit += f" {target.pct}%"
        bits.append(bit)
    return ", ".join(bits)


def _change(label: str, before: str | None, after: str | None) -> str | None:
    if before == after:
        return None
    if before is None:
        return f"{label} {after}"
    if after is None:
        return f"{label} {before} cleared"
    return f"{label} {before}{_ARROW}{after}"


def _float_text(raw: float | None) -> str | None:
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if raw != raw or raw in (float("inf"), float("-inf")) or raw <= 0:
        return None
    try:
        dec = Decimal(str(raw))
    except InvalidOperation:
        return None
    if not dec.is_finite() or dec <= 0:
        return None
    return fmt_decimal(dec)
