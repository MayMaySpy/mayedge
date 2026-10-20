"""Planner manage phase. PlannerRunner calls these; the rules stay in docs/planner-rules.md."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.ledger import Clip
from mayedge.algos.planner import venue
from mayedge.algos.planner.config import (
    MISMATCH_GRACE_MS,
    MISSING_GRACE_MS,
)
from mayedge.algos.planner.plan import (
    PlannedStep,
    PlannedTarget,
    resize_targets,
    stop_price,
    trail_price_distance,
)
from mayedge.algos.trail import engine
from mayedge.algos.trail.engine import Point
from mayedge.numbers import fmt_decimal

if TYPE_CHECKING:
    from mayedge.algos.planner.job import PlannerRunner

ZERO = Decimal("0")


def _fmt(d: Decimal | None) -> str | None:
    return fmt_decimal(d)


def _sign(side: str) -> int:
    return 1 if side == "buy" else -1


async def _evaluate_manage(runner: PlannerRunner, now: int, prices: list[Decimal]) -> None:
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    pos, _ = runner._held()
    if pos == 0:
        # N1: flat, by the stop, the last target or the operator.
        runner._flat_since = runner._flat_since or now
        if now - runner._flat_since < MISSING_GRACE_MS:
            return
        await runner._cancel_all()
        st.status = ChaseStatus.DONE
        st.reason = "flat"
        runner._book.finish(runner)
        return
    runner._flat_since = None
    expected = st.entry_filled - runner._tp_filled()
    half = runner._qty_step() / 2
    for clip in runner._tp_clips():
        if clip.status != "live" or clip.missing_since is None:
            continue
        if pos <= expected - clip.remaining + half:
            # Gone from the book and the Position is smaller by it: a fill,
            # even when the feed never showed it resting.
            clip.seen_on_book = True
            st.ledger.close_missing(clip, canceling=False, now=now)
            expected = st.entry_filled - runner._tp_filled()
        elif runner._gone(clip, now):
            clip.status = "cancelled"
            clip.closed_at = now
    st.expected_size = expected
    if abs(pos - expected) > half:
        runner._mismatch_since = runner._mismatch_since or now
        if now - runner._mismatch_since >= MISMATCH_GRACE_MS and st.status == ChaseStatus.RUNNING:
            if pos < expected:
                # M6: smaller by an outside close. Targets take their share of what is left.
                # Not while a target's own fill may still be on its way: that is not outside.
                pending = st.trail_fired or any(
                    c.status == "live" and c.missing_since is not None for c in runner._tp_clips()
                )
                if not pending:
                    resize_to_position(runner, pos)
                    st.reason = f"Position reduced to {_fmt(pos)}: targets resized"
            else:
                st.status = ChaseStatus.PAUSED
                st.reason = "position changed"  # M6
    else:
        runner._mismatch_since = None
    if st.status != ChaseStatus.RUNNING:
        return
    stop = runner._live("stop")
    if stop is not None and runner._gone(stop, now):
        # The Position is still open and its stop is gone. Put it back.
        stop.status = "cancelled"
        stop.closed_at = now
        stop = None
    if stop is None and "stop" not in runner._gave_up:
        await runner._place_stop()
    await runner._place_targets()
    await runner._take_step()
    if st.status == ChaseStatus.RUNNING and st.phase == "managing":
        await runner._trail_stop(now, prices)
    if st.status == ChaseStatus.RUNNING and st.phase == "managing":
        await runner._trail_targets(now, prices)

def resize_to_position(runner: PlannerRunner, pos: Decimal) -> None:
    """M6: resize every target's unfilled part to its share of ``pos``. The venue follows in _place_targets."""
    st = runner._state
    assert st.plan is not None and st.params is not None
    filled: dict[int, Decimal] = {}
    for clip in runner._tp_clips():
        role = runner._role(clip)
        if role.startswith("tp") and role[2:].isdigit():
            filled[int(role[2:])] = filled.get(int(role[2:]), ZERO) + min(clip.filled, clip.qty)
    ctx, _ = venue.market_context(runner._exec(), st.market_index)
    st.plan, _ = resize_targets(
        st.plan,
        filled=filled,
        expected=st.expected_size,
        held=pos,
        stop_steps=st.params.stop_steps,
        ctx=ctx,
    )
    st.entry_filled = pos + runner._tp_filled()
    st.expected_size = pos
    runner._mismatch_since = None
    # A target dropped for the venue minimum may go back on at a new size.
    runner._gave_up = {r for r in runner._gave_up if not r.startswith("tp")}


def _wrong_size(clip: Clip, left: Decimal, half: Decimal) -> bool:
    """A live target that no longer closes what its target has left (M6)."""
    return abs(clip.remaining - left) > half


def _due_step(runner: PlannerRunner) -> PlannedStep | None:
    """The furthest Stop step whose target has filled in full and is not taken yet."""
    st = runner._state
    assert st.plan is not None
    due: PlannedStep | None = None
    for step in st.plan.steps:
        if step.after <= st.steps_done:
            continue
        tp = runner._latest(f"tp{step.after}")
        if tp is not None and tp.status == "filled" and tp.filled >= tp.qty:
            due = step
    return due

async def _take_step(runner: PlannerRunner) -> None:
    """M2–M4 and M9: step the stop toward profit, once per step, never back."""
    st = runner._state
    assert st.plan is not None
    step = runner._due_step()
    if step is None:
        return
    price = runner._step_price(step)
    current = st.stop_trigger if st.stop_trigger is not None else st.plan.stop
    if (price - current) * _sign(runner._side()) <= 0:
        st.steps_done = step.after
        return
    stop = runner._live("stop")
    if stop is None:
        return
    await runner._await_order_index(stop)
    if not stop.order_index:
        return
    ex = runner._exec()
    if ex.amend_trigger_leg is None:
        raise RuntimeError("trigger amend is not wired")
    p = st.params
    name = "breakeven" if step.to == "breakeven" else step.to.upper()
    try:
        await ex.amend_trigger_leg(
            st.market_index,
            stop.order_index,
            runner._close_side(),
            role="sl",
            kind="market",
            trigger=_fmt(price) or "0",
            slippage=p.slippage if p else 0.01,
        )
    except ValueError as e:
        if "wrong side of mark" not in str(e):
            raise
        if step.to == "breakeven":
            st.reason = "breakeven waits for mark to clear it"
            return
        # M9: price is already back through the step; take the exit it promised.
        await runner._close_at_market()
        st.steps_done = step.after
        st.reason = f"mark passed the step to {name}: closed at market"
        return
    stop.price = price
    st.stop_trigger = price
    st.steps_done = step.after
    st.reason = f"stop at {name}"

def _step_price(runner: PlannerRunner, step: PlannedStep) -> Decimal:
    """M2: a step to a Trail target goes to the price it filled at."""
    st = runner._state
    assert st.plan is not None
    if not step.to.startswith("tp"):
        return step.price
    target = next((t for t in st.plan.targets if f"tp{t.index}" == step.to), None)
    if target is None or target.order != "trail":
        return step.price
    seqs = {c.seq for c in st.ledger.clips if runner._role(c) == step.to}
    fills = [f for f in st.ledger.fills if f.clip_seq in seqs]
    qty = sum((f.qty for f in fills), ZERO)
    if qty <= 0:
        return step.price
    avg = sum((f.price * f.qty for f in fills), ZERO) / qty
    return stop_price(runner._side(), avg, runner._tick())

async def _trail_stop(runner: PlannerRunner, now: int, prices: list[Decimal]) -> None:
    """M10: past its start the stop follows the best price, never below the stepped stop."""
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    ts = p.trail_stop
    stop = runner._live("stop")
    if ts is None or stop is None or not runner._trail_stop_started():
        return
    distance, kind = trail_price_distance(ts.unit, ts.distance, plan.r)
    activation = None
    if ts.start == "r" and ts.at_r is not None:
        activation = plan.entry + _sign(p.side) * plan.r * ts.at_r
    current = st.stop_trigger if st.stop_trigger is not None else plan.stop
    f = runner._leg_follow(distance, kind, activation=activation, floor=current)
    point = st.trails.get("stop", Point())
    for px in prices:
        point = engine.follow(f, point, px)
        trigger = point.trigger
        if p.reference == "last" and trigger is not None and engine.crossed(f, trigger, px):
            st.trails["stop"] = point
            await runner._close_at_market()  # Trail L1
            st.reason = f"trail stop: closed at market at {_fmt(px)}"
            return
    st.trails["stop"] = point
    if not point.active or point.trigger is None:
        return
    wanted = runner._venue_wanted(f, point)
    if not runner._move_due("stop", f, venue_at=current, wanted=wanted, best=point.best or wanted, now=now):
        return
    moved = await runner._amend_trigger(stop, wanted)
    if moved is None:
        return
    if not moved:
        await runner._close_at_market()  # M9, Trail V2
        st.reason = "mark passed the trail stop: closed at market"
        return
    st.stop_trigger = wanted
    st.trail_moves["stop"] = now
    st.reason = f"stop trailing at {_fmt(wanted)}"

async def _trail_targets(runner: PlannerRunner, now: int, prices: list[Decimal]) -> None:
    """P9 Trail: at its price a target puts on a reduce-only Stop for its size, and follows."""
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    for t in plan.targets:
        if t.order == "trail" and t.trail_distance is not None:
            await runner._trail_target(t, now, prices)
            if st.status != ChaseStatus.RUNNING:
                return

async def _trail_target(runner: PlannerRunner, t: PlannedTarget, now: int, prices: list[Decimal]) -> None:
    st = runner._state
    p = st.params
    assert p is not None and t.trail_distance is not None
    role = f"tp{t.index}"
    if role in runner._gave_up:
        return
    clips = [c for c in st.ledger.clips if runner._role(c) == role]
    left = t.qty - sum((c.filled for c in clips), ZERO)
    live = [c for c in clips if c.status == "live"]
    if left <= 0:
        return
    if role in st.trail_fired:
        if live:
            return  # the fire is out; the fill or the grace decides
        st.trail_fired.discard(role)
    f = runner._leg_follow(t.trail_distance, t.trail_kind, activation=t.price, floor=None)
    point = st.trails.get(role, Point())
    for px in prices:
        point = engine.follow(f, point, px)
        trigger = point.trigger
        if p.reference == "last" and trigger is not None and engine.crossed(f, trigger, px):
            st.trails[role] = point
            await runner._fire_target(role, live, left, px)
            return
    st.trails[role] = point
    if not point.active or point.trigger is None:
        return
    wanted = runner._venue_wanted(f, point)
    clip = live[0] if live else None
    if clip is not None and _wrong_size(clip, left, runner._qty_step() / 2):
        if not await runner._cancel_clip(clip):
            return
        clip = None
    if clip is None:
        clip = runner._place(role, price=wanted, qty=left)
        try:
            await runner._send_trigger(clip, role="sl", kind="market", size=left, trigger=wanted)
        except ValueError as e:
            if "wrong side of mark" not in str(e):
                runner._gave_up.add(role)
                st.reason = f"target {t.index} refused: {e}"
                return
            await runner._fire_target(role, [], left, runner._mark())  # Trail V2
            return
        st.trail_moves[role] = now
        st.reason = f"TP{t.index} trailing at {_fmt(wanted)}"
        return
    if not runner._move_due(role, f, venue_at=clip.price, wanted=wanted, best=point.best or wanted, now=now):
        return
    moved = await runner._amend_trigger(clip, wanted)
    if moved is None:
        return
    if not moved:
        await runner._fire_target(role, [clip], left, runner._mark())
        return
    st.trail_moves[role] = now

async def _fire_target(runner: PlannerRunner, role: str, live: list[Clip], left: Decimal, px: Decimal) -> None:
    """Trail L1, L3: close the target's size at market, then pull its backstop."""
    st = runner._state
    p = st.params
    assert p is not None
    pos, _ = runner._held()
    qty = min(left, pos)
    if qty <= 0:
        return
    clip = runner._place(role, price=px, qty=qty)
    await runner._exec().create_market_order(
        market_index=st.market_index,
        side=runner._close_side(),
        size=_fmt(qty),
        slippage=p.slippage,
        reduce_only=True,
        client_order_index=clip.client_order_index,
    )
    st.trail_fired.add(role)
    for c in live:
        await runner._cancel_clip(c)
    st.reason = f"{role.upper()} fired at {_fmt(px)}"

