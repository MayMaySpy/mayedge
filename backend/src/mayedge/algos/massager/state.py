"""Massager job state."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from mayedge.algos.chase.state import ClipState
from mayedge.algos.massager.plan import Book, MassagerParams


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
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> MassagerRuntime:
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
        )


@dataclass(kw_only=True)
class MassagerState(ClipState):
    params: MassagerParams | None = None
    runtime: MassagerRuntime = field(default_factory=MassagerRuntime)
