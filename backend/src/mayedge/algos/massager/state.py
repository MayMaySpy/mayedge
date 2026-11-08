"""Massager job state."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.state import ClipState
from mayedge.algos.massager.plan import Book, MassagerParams, Tally
from mayedge.rows import obj


def _dec_or_none(raw: Any) -> Decimal | None:
    return Decimal(str(raw)) if raw not in (None, "") else None


@dataclass
class MassagerRuntime:
    """What a run keeps beyond its Clips. Persisted inside params_json."""

    book: Book = field(default_factory=Book)
    core_side: int = 0
    core: Decimal = Decimal("0")
    core_entry: Decimal = Decimal("0")
    catching: bool = False
    catch_level: int = 0
    clip_levels: dict[int, int] = field(default_factory=dict)
    catch_seqs: set[int] = field(default_factory=set)
    handled: dict[int, Decimal] = field(default_factory=dict)
    pending_core: Decimal | None = None
    pending_since: int = 0
    # MS9: the price the levels step out from. None until the catch-up is paid.
    anchor: Decimal | None = None
    # MS21: the Step the levels rest at, the last ATR read, and when they last moved.
    step: Decimal = Decimal("0")
    clip_marks: dict[int, Decimal] = field(default_factory=dict)
    atr: Decimal | None = None
    step_moved_at: int = 0
    atr_next_at: int = 0
    # MS22: the Position's record across runs. None only on a run kept before it (MS16).
    tally: Tally | None = None
    # MS22: whether a Start carried the Tally, why, and from which run.
    carried: bool = False
    carry_why: str | None = None
    carried_from: str | None = None
    # MS23: when the next 1h close is read, and the close that paused the run.
    band_next_at: int = 0
    band_close: Decimal | None = None
    band_close_at: int = 0
    # MS24: the Chop reading the ticket sent at Start.
    chop: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "book": self.book.to_json(),
            "core_side": self.core_side,
            "core": str(self.core),
            "core_entry": str(self.core_entry),
            "catching": self.catching,
            "catch_level": self.catch_level,
            "clip_levels": {str(k): v for k, v in self.clip_levels.items()},
            "catch_seqs": sorted(self.catch_seqs),
            "handled": {str(k): str(v) for k, v in self.handled.items()},
            "anchor": str(self.anchor) if self.anchor is not None else None,
            "step": str(self.step),
            "clip_marks": {str(k): str(v) for k, v in self.clip_marks.items()},
            "atr": str(self.atr) if self.atr is not None else None,
            "step_moved_at": self.step_moved_at,
            "tally": self.tally.to_json() if self.tally is not None else None,
            "carried": self.carried,
            "carry_why": self.carry_why,
            "carried_from": self.carried_from,
            "band_close": str(self.band_close) if self.band_close is not None else None,
            "band_close_at": self.band_close_at,
            "chop": self.chop,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> MassagerRuntime:
        tally, chop = obj(raw.get("tally")), obj(raw.get("chop"))
        return cls(
            book=Book.from_json(dict(raw.get("book") or {})),
            core_side=int(raw.get("core_side") or 0),
            core=Decimal(str(raw.get("core") or "0")),
            core_entry=Decimal(str(raw.get("core_entry") or "0")),
            catching=bool(raw.get("catching")),
            catch_level=int(raw.get("catch_level") or 0),
            clip_levels={int(k): int(v) for k, v in dict(raw.get("clip_levels") or {}).items()},
            catch_seqs={int(x) for x in raw.get("catch_seqs") or ()},
            handled={int(k): Decimal(str(v)) for k, v in dict(raw.get("handled") or {}).items()},
            anchor=_dec_or_none(raw.get("anchor")),
            step=Decimal(str(raw.get("step") or "0")),
            clip_marks={
                int(k): Decimal(str(v)) for k, v in dict(raw.get("clip_marks") or {}).items()
            },
            atr=_dec_or_none(raw.get("atr")),
            step_moved_at=int(raw.get("step_moved_at") or 0),
            tally=Tally.from_json(tally) if tally else None,
            carried=bool(raw.get("carried")),
            carry_why=str(raw["carry_why"]) if raw.get("carry_why") else None,
            carried_from=str(raw["carried_from"]) if raw.get("carried_from") else None,
            band_close=_dec_or_none(raw.get("band_close")),
            band_close_at=int(raw.get("band_close_at") or 0),
            chop=chop or None,
        )


@dataclass(kw_only=True)
class MassagerState(ClipState):
    params: MassagerParams | None = None
    runtime: MassagerRuntime = field(default_factory=MassagerRuntime)
