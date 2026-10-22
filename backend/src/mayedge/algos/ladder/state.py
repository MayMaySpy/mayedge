"""Ladder job state."""

from __future__ import annotations

from dataclasses import dataclass

from mayedge.algos.chase.state import ClipState
from mayedge.algos.ladder.plan import LadderParams


@dataclass(kw_only=True)
class LadderState(ClipState):
    params: LadderParams | None = None
