"""Ladder job state."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.iceberg import Action
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.ladder.plan import LadderParams
from mayedge.algos.ledger import Ledger

if TYPE_CHECKING:
    from mayedge.algos.ladder.job import LadderRunner


@dataclass
class LadderState:
    status: ChaseStatus = ChaseStatus.STOPPED
    params: LadderParams | None = None
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


class LadderBookView(Protocol):
    def publish(self) -> None: ...
    def finish(self, job: LadderRunner) -> None: ...
    def alloc_coi(self) -> int: ...
    def execution(self) -> ChaseExecution: ...

    @property
    def missing_fill_grace_ms(self) -> int: ...
