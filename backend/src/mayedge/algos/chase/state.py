"""Chase job state and status types."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from mayedge.algos.chase.iceberg import Action, ChaseIcebergParams
from mayedge.algos.ledger import Ledger
from mayedge.algos.chase.execution import ChaseExecution

if TYPE_CHECKING:
    from mayedge.algos.chase.job import ChaseIcebergRunner


class ChaseStatus(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"


ACTIVE_STATUSES = (ChaseStatus.RUNNING, ChaseStatus.PAUSED, ChaseStatus.ERROR)


@dataclass
class ChaseState:
    status: ChaseStatus = ChaseStatus.STOPPED
    params: ChaseIcebergParams | None = None
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


class ChaseBookView(Protocol):
    """What a job needs from its book — keeps chase_job from importing chase_book."""

    def publish(self) -> None: ...
    def finish(self, job: ChaseIcebergRunner) -> None: ...
    def alloc_coi(self) -> int: ...
    def execution(self) -> ChaseExecution: ...

    @property
    def missing_fill_grace_ms(self) -> int: ...
