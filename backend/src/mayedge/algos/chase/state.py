"""Chase job state and status types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.iceberg import Action, ChaseIcebergParams
from mayedge.algos.ledger import Ledger
from mayedge.numbers import to_decimal


class ChaseStatus(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"

    @classmethod
    def of(cls, raw: object) -> ChaseStatus:
        """A stored status. Anything unknown reads as stopped."""
        try:
            return cls(raw or "stopped")
        except ValueError:
            return cls.STOPPED


ACTIVE_STATUSES = (ChaseStatus.RUNNING, ChaseStatus.PAUSED, ChaseStatus.ERROR)


def _dec_or_none(raw: object) -> Decimal | None:
    return None if raw is None else to_decimal(raw)


@dataclass(kw_only=True)
class ClipState:
    """What every clip job keeps. Chase, Ladder and Grid add their params."""

    status: ChaseStatus = ChaseStatus.STOPPED
    market_index: int = 0
    symbol: str = ""
    reduce_only: bool = False
    remaining: Decimal = Decimal("0")
    filled: Decimal = Decimal("0")
    quote_action: str = Action.PAUSE.value
    reason: str | None = None
    rest_price: Decimal | None = None
    rest_qty: Decimal | None = None
    error: str | None = None
    algo_id: str = ""
    created_at: int = 0
    ledger: Ledger = field(default_factory=Ledger)

    @staticmethod
    def fields_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
        """The shared fields of a stored run, as keyword arguments for a state."""
        return {
            "status": ChaseStatus.of(row.get("status")),
            "market_index": int(row.get("market_index") or 0),
            "symbol": str(row.get("symbol") or ""),
            "reduce_only": bool(row.get("reduce_only")),
            "remaining": to_decimal(row.get("remaining") or "0"),
            "filled": to_decimal(row.get("filled") or "0"),
            "quote_action": str(row.get("quote_action") or Action.PAUSE.value),
            "reason": row.get("reason"),
            "rest_price": _dec_or_none(row.get("rest_price")),
            "rest_qty": _dec_or_none(row.get("rest_qty")),
            "error": row.get("error"),
            "algo_id": str(row.get("algo_id") or ""),
            "created_at": int(row.get("created_at") or 0),
            "ledger": Ledger.from_row(row),
        }


@dataclass(kw_only=True)
class ChaseState(ClipState):
    params: ChaseIcebergParams | None = None


class ClipBookView(Protocol):
    """What a clip job needs from its book, so a job never imports its book."""

    def publish(self) -> None: ...
    def finish(self, job: Any) -> None: ...
    def alloc_coi(self) -> int: ...
    def execution(self) -> ChaseExecution: ...

    @property
    def missing_fill_grace_ms(self) -> int: ...
