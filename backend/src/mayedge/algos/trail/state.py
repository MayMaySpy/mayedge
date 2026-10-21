"""Trail job state."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.ledger import Ledger
from mayedge.algos.trail.engine import Point, Side
from mayedge.algos.trail.plan import TrailParams
from mayedge.numbers import fmt_decimal, parse_decimal
from mayedge.rows import is_obj, obj

if TYPE_CHECKING:
    from mayedge.algos.trail.job import TrailRunner


@dataclass
class TrailState:
    status: ChaseStatus = ChaseStatus.STOPPED
    params: TrailParams | None = None
    side: Side = "sell"
    # Entry: its size. Take Profit: its share of the Position. Stop: 0, tied to the Position.
    qty: Decimal = Decimal("0")
    # A Stop's start price: the trigger is never worse (TS2).
    floor: Decimal | None = None
    market_index: int = 0
    symbol: str = ""
    algo_id: str = ""
    created_at: int = 0
    reason: str | None = None
    error: str | None = None
    ledger: Ledger = field(default_factory=Ledger)
    # clip seq → "stop" (the venue Stop or backstop) or "fire" (a Market order the desk sent)
    roles: dict[int, str] = field(default_factory=dict)
    point: Point = field(default_factory=Point)
    # Where the venue Stop's trigger is.
    venue_trigger: Decimal | None = None
    last_move_ms: int | None = None
    # The Position on the Trail's side when its Take Profit stop or a fire went on.
    held_before: Decimal = Decimal("0")
    fired_at: int | None = None
    fired_price: Decimal | None = None
    deadline_ms: int | None = None
    following: bool = True

    def runtime_json(self) -> dict[str, Any]:
        p = self.point
        return {
            "side": self.side,
            "qty": fmt_decimal(self.qty) or "0",
            "floor": fmt_decimal(self.floor),
            "active": p.active,
            "best": fmt_decimal(p.best),
            "trigger": fmt_decimal(p.trigger),
            "venue_trigger": fmt_decimal(self.venue_trigger),
            "last_move_ms": self.last_move_ms,
            "held_before": fmt_decimal(self.held_before) or "0",
            "fired_at": self.fired_at,
            "fired_price": fmt_decimal(self.fired_price),
            "deadline_ms": self.deadline_ms,
            "following": self.following,
            "roles": {str(k): v for k, v in self.roles.items()},
        }

    def load_runtime(self, raw: dict[str, Any]) -> None:
        self.side = "buy" if raw.get("side") == "buy" else "sell"
        qty = raw.get("qty")
        self.qty = parse_decimal(qty) if qty not in (None, "") else Decimal("0")
        floor = raw.get("floor")
        self.floor = parse_decimal(floor) if floor not in (None, "") else None
        best = raw.get("best")
        trigger = raw.get("trigger")
        self.point = Point(
            active=bool(raw.get("active")),
            best=parse_decimal(best) if best not in (None, "") else None,
            trigger=parse_decimal(trigger) if trigger not in (None, "") else None,
        )
        venue_trigger = raw.get("venue_trigger")
        self.venue_trigger = (
            parse_decimal(venue_trigger) if venue_trigger not in (None, "") else None
        )
        last = raw.get("last_move_ms")
        self.last_move_ms = int(last) if last else None
        held = raw.get("held_before")
        self.held_before = parse_decimal(held) if held not in (None, "") else Decimal("0")
        fired = raw.get("fired_at")
        self.fired_at = int(fired) if fired else None
        fired_price = raw.get("fired_price")
        self.fired_price = parse_decimal(fired_price) if fired_price not in (None, "") else None
        deadline = raw.get("deadline_ms")
        self.deadline_ms = int(deadline) if deadline else None
        roles = obj(raw.get("roles"))
        self.roles = {int(k): str(v) for k, v in roles.items()} if is_obj(roles) else {}


class TrailBookView(Protocol):
    def publish(self) -> None: ...
    def finish(self, job: TrailRunner) -> None: ...
    def alloc_coi(self) -> int: ...
    def execution(self) -> ChaseExecution: ...
    def take_amend(self, market_index: int, now_ms: int) -> bool: ...
