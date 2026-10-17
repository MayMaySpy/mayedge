"""Planner job state."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.ledger import Ledger
from mayedge.algos.planner.plan import Plan, PlannerParams
from mayedge.numbers import fmt_decimal

if TYPE_CHECKING:
    from mayedge.algos.planner.job import PlannerRunner

Phase = Literal["entering", "managing"]


@dataclass
class PlannerState:
    status: ChaseStatus = ChaseStatus.STOPPED
    phase: Phase = "entering"
    params: PlannerParams | None = None
    plan: Plan | None = None
    market_index: int = 0
    symbol: str = ""
    algo_id: str = ""
    created_at: int = 0
    reason: str | None = None
    error: str | None = None
    ledger: Ledger = field(default_factory=Ledger)
    # clip seq → "entry", "stop", "tp1"…
    roles: dict[int, str] = field(default_factory=dict)
    entry_filled: Decimal = Decimal("0")
    # What the Position should be from Planner's own fills (M6).
    expected_size: Decimal = Decimal("0")
    stop_trigger: Decimal | None = None
    breakeven_done: bool = False
    entry_deadline_ms: int | None = None

    def runtime_json(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "plan": self.plan.to_json() if self.plan else None,
            "roles": {str(k): v for k, v in self.roles.items()},
            "entry_filled": fmt_decimal(self.entry_filled) or "0",
            "expected_size": fmt_decimal(self.expected_size) or "0",
            "stop_trigger": fmt_decimal(self.stop_trigger),
            "breakeven_done": self.breakeven_done,
            "entry_deadline_ms": self.entry_deadline_ms,
        }

    def load_runtime(self, raw: dict[str, Any]) -> None:
        phase = raw.get("phase")
        self.phase = "managing" if phase == "managing" else "entering"
        plan = raw.get("plan")
        self.plan = Plan.from_json(plan) if isinstance(plan, dict) else None
        roles = raw.get("roles") or {}
        self.roles = {int(k): str(v) for k, v in roles.items()} if isinstance(roles, dict) else {}
        self.entry_filled = Decimal(str(raw.get("entry_filled") or "0"))
        self.expected_size = Decimal(str(raw.get("expected_size") or "0"))
        trigger = raw.get("stop_trigger")
        self.stop_trigger = Decimal(str(trigger)) if trigger not in (None, "") else None
        self.breakeven_done = bool(raw.get("breakeven_done"))
        deadline = raw.get("entry_deadline_ms")
        self.entry_deadline_ms = int(deadline) if deadline else None


class PlannerBookView(Protocol):
    def publish(self) -> None: ...
    def finish(self, job: PlannerRunner) -> None: ...
    def alloc_coi(self) -> int: ...
    def execution(self) -> ChaseExecution: ...
