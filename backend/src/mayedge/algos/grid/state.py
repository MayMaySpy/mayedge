"""Chase-grid job state."""

from __future__ import annotations

from dataclasses import dataclass, field

from mayedge.algos.chase.state import ACTIVE_STATUSES, ChaseStatus, ClipState
from mayedge.algos.grid.decide import GridParams, GridRuntime


@dataclass(kw_only=True)
class GridState(ClipState):
    params: GridParams | None = None
    runtime: GridRuntime = field(default_factory=GridRuntime)


__all__ = ["ACTIVE_STATUSES", "ChaseStatus", "GridState"]
