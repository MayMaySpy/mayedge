"""Planner entry phase. PlannerRunner calls these; the rules stay in docs/planner-rules.md."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import TYPE_CHECKING

from mayedge.algos.chase.config import ACK_WAIT_MS, MIN_REQUOTE_MS
from mayedge.algos.chase.iceberg import Action, ChaseIcebergParams, decide
from mayedge.algos.chase.state import ChaseStatus
from mayedge.algos.ladder.plan import Rung, is_passive, sort_by_closeness
from mayedge.algos.ledger import Clip
from mayedge.algos.planner import venue
from mayedge.algos.planner.config import (
    ACK_GRACE_MS,
    MARKET_ENTRY_GRACE_MS,
    MISSING_GRACE_MS,
    RATE_LIMIT_COOLDOWN_MS,
    RUNG_TX_RESERVE,
)
from mayedge.algos.planner.plan import (
    PlanRefused,
    entry_follow,
    plan_size,
    price_plan,
    round_qty,
)
from mayedge.algos.trail import engine
from mayedge.algos.trail.engine import Point
from mayedge.config import settings
from mayedge.lighter.budget import BudgetRefused, budget
from mayedge.lighter.errors import is_blocked, is_min_size, is_order_not_found, is_would_cross
from mayedge.numbers import check_notional, fmt_decimal

if TYPE_CHECKING:
    from mayedge.algos.planner.job import PlannerRunner

ZERO = Decimal("0")


def _sign(side: str) -> int:
    return 1 if side == "buy" else -1


async def _evaluate_entry(runner: PlannerRunner, now: int, prices: list[Decimal]) -> None:
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    if p.entry_type == "chase":
        await runner._work_chase(now)
        return
    if p.entry_type == "ladder":
        await runner._work_ladder(now)
        return
    entry = runner._latest("entry")
    if entry is None:
        if p.entry_type == "trail":
            await runner._track_entry(now, prices)
            return
        raise RuntimeError("planner entering with no entry")
    pos, avg = runner._held()
    filled = max(min(entry.filled, plan.size), min(max(pos, ZERO), plan.size))
    st.entry_filled = filled
    if filled > 0 and runner._live("stop") is None and "stop" not in runner._gave_up:
        await runner._place_stop()
    if st.status != ChaseStatus.RUNNING:
        return
    half = runner._qty_step() / 2
    if entry.status == "live":
        mark = runner._mark()
        if filled >= plan.size - half:
            entry.status = "filled"
            entry.closed_at = now
        elif mark > 0 and (mark - plan.stop) * _sign(p.side) <= 0:
            if await runner._cancel_clip(entry):
                st.reason = "stop reached before the entry filled"  # E4
        elif st.entry_deadline_ms and now >= st.entry_deadline_ms:
            if await runner._cancel_clip(entry):
                st.reason = "entry expired"  # E5
        elif st.finish_entry:
            if await runner._cancel_clip(entry):
                st.reason = "entry ended early"  # E14
        else:
            gone = entry.missing_since is not None and (
                now - entry.missing_since >= MISSING_GRACE_MS
            )
            # A Market entry may come and go between two account updates.
            market_over = (
                p.entry_type in ("market", "trail")
                and not entry.seen_on_book
                and now - entry.placed_at >= MARKET_ENTRY_GRACE_MS
            )
            if gone or market_over:
                entry.status = "filled" if filled > 0 else "cancelled"
                entry.closed_at = now
    if entry.status == "live":
        return
    await runner._entry_over(now, filled, avg, closed_at=entry.closed_at)


async def _work_chase(runner: PlannerRunner, now: int) -> None:
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None and p.entry_chase is not None
    ec = p.entry_chase
    clips = [c for c in st.ledger.clips if runner._role(c) == "entry"]
    pos, avg = runner._held()
    traded = sum((min(c.filled, c.qty) for c in clips), ZERO)
    # E7, E13: the trades or the Position, whichever shows more, never past the plan.
    filled = min(plan.size, max(traded, pos, ZERO))
    st.entry_filled = filled
    if filled > 0 and runner._live("stop") is None and "stop" not in runner._gave_up:
        await runner._place_stop()  # E2
    if st.status != ChaseStatus.RUNNING:
        return
    live = runner._live("entry")
    half = runner._qty_step() / 2
    mark = runner._mark()
    over: str | None = None
    if filled >= plan.size - half:
        over = "entry filled"
    elif mark > 0 and (mark - plan.stop) * _sign(p.side) <= 0:
        over = "stop reached before the entry filled"  # E4
    elif st.entry_deadline_ms and now >= st.entry_deadline_ms:
        over = "entry expired"  # E5
    elif st.finish_entry:
        over = "entry ended early"  # E14
    if over is not None:
        if live is not None and not await runner._cancel_clip(live):
            return
        if over != "entry filled":
            st.reason = over
        last = runner._latest("entry")
        await runner._entry_over(now, filled, avg, closed_at=last.closed_at if last else now)
        return
    if live is not None:
        before = sum((min(c.filled, c.qty) for c in clips if c is not live), ZERO)
        if live.filled >= live.qty - half or pos >= before + live.qty - half:
            # The trades or the Position account for all of it (E7: the Position is evidence).
            live.filled = max(live.filled, live.qty)
            live.status = "filled"
            live.closed_at = now
            live = None
    if live is not None and not live.seen_on_book and now - live.placed_at >= ACK_GRACE_MS:
        # Never shown on the book: the venue did not take it (post-only, say).
        live.missing_since = live.missing_since or now - MISSING_GRACE_MS
    if live is not None and runner._gone(live, now):
        # Off the book and not accounted for: wait for the evidence (E13).
        live.status = "cancelled"
        live.closed_at = now
        live = None
        runner._entry_vanished_ms = now
    if (
        live is None
        and runner._entry_vanished_ms
        and now - runner._entry_vanished_ms < MISSING_GRACE_MS
    ):
        st.reason = "entry waits for the last Clip's fills"  # E13
        return
    view = runner._chase_view()
    remaining = plan.size - filled
    quote = None
    if view is not None:
        quote = decide(
            ChaseIcebergParams(
                side=p.side,
                qty=plan.size,
                display_qty=ec.clip if ec.clip is not None else remaining,
                offset_bps=ec.offset_bps,
                price_floor=ec.low,
                price_ceiling=ec.high,
            ),
            view,
            remaining,
        )
    if quote is None or quote.action != Action.REST:
        reason = "book not synced" if quote is None else (quote.reason or "waiting")
        if quote is not None and quote.reason == "below_min_qty" and filled > 0:
            # What is left is under the venue minimum: the entry is as full as it gets.
            if live is not None and not await runner._cancel_clip(live):
                return
            await runner._entry_over(now, filled, avg, closed_at=now)
            return
        if live is not None:
            await runner._cancel_clip(live)
        st.reason = f"entry waits: {reason.replace('_', ' ')}"
        return
    assert quote.price is not None and quote.qty is not None
    if live is None:
        await runner._rest_entry(quote.price, quote.qty, now)
        return
    if live.price == quote.price:
        st.reason = f"entry resting at {fmt_decimal(live.price)}"
        return
    if not live.seen_on_book and now - live.placed_at < ACK_WAIT_MS:
        return
    if now - runner._entry_moved_ms < MIN_REQUOTE_MS:
        return
    await runner._amend_chase(live, quote.price, now)


async def _rest_entry(runner: PlannerRunner, price: Decimal, qty: Decimal, now: int) -> str | None:
    """A post-only entry Clip: a Chase entry's (E10) or a Ladder rung (EL1).

    None once sent, or why the venue refused it: "cross" or "min".
    """
    st = runner._state
    p = st.params
    assert p is not None
    clip = runner._place("entry", price=price, qty=qty)
    try:
        await runner._exec().create_limit_order(
            market_index=st.market_index,
            side=p.side,
            size=fmt_decimal(qty),
            price=fmt_decimal(price),
            time_in_force="post_only",
            reduce_only=False,
            client_order_index=clip.client_order_index,
        )
    except Exception as e:
        clip.status = "cancelled"
        clip.closed_at = now
        if is_would_cross(e) or is_min_size(e):
            st.reason = f"entry waits: {e}"
            return "min" if is_min_size(e) else "cross"
        raise
    runner._entry_moved_ms = now
    st.reason = f"entry resting at {fmt_decimal(price)}"
    return None


async def _amend_chase(runner: PlannerRunner, clip: Clip, price: Decimal, now: int) -> None:
    """E10: move the Clip in place as the book walks."""
    await runner._await_order_index(clip)
    if not clip.order_index or clip.status != "live":
        return
    try:
        await runner._exec().modify_order(
            market_index=runner._state.market_index,
            order_index=clip.order_index,
            price=fmt_decimal(price) or "0",
            size=fmt_decimal(clip.remaining if clip.remaining > 0 else clip.qty) or "0",
        )
    except Exception as e:
        if is_would_cross(e):
            runner._entry_moved_ms = now  # keep the resting price; try again later
            return
        if is_order_not_found(e):
            clip.missing_since = clip.missing_since or now
            return
        raise
    runner._state.ledger.amend(clip, price=price, now=now)
    runner._entry_moved_ms = now
    runner._state.reason = f"entry resting at {fmt_decimal(price)}"


async def _work_ladder(runner: PlannerRunner, now: int) -> None:
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    clips = [c for c in st.ledger.clips if runner._role(c) == "entry"]
    pos, avg = runner._held()
    half = runner._qty_step() / 2
    traded = sum((min(c.filled, c.qty) for c in clips), ZERO)
    for c in clips:
        if c.status != "live":
            continue
        if not c.seen_on_book and now - c.placed_at >= ACK_GRACE_MS:
            # Never shown on the book: the venue did not take it (post-only, say).
            c.missing_since = c.missing_since or now - MISSING_GRACE_MS
        if not runner._gone(c, now):
            continue
        if pos >= traded + c.remaining - half:
            # The Position shows more than the trades by this rung: a fill (E7).
            traded += c.remaining
            c.filled = c.qty
            c.status = "filled"
        else:
            # Off the book and not accounted for: wait for the evidence, then rest it again (E13).
            c.status = "cancelled"
            runner._entry_vanished_ms = now
        c.closed_at = now
    # E7: the trades or the Position, whichever shows more, never past the plan.
    filled = min(plan.size, max(traded, pos, ZERO))
    st.entry_filled = filled
    if filled > 0 and runner._live("stop") is None and "stop" not in runner._gave_up:
        await runner._place_stop()  # E2
    if st.status != ChaseStatus.RUNNING:
        return
    live = [c for c in clips if c.status == "live"]
    pending = runner._pending_rungs(plan.rungs, clips, half)
    mark = runner._mark()
    over: str | None = None
    if (not pending and not live) or filled >= plan.size - half:
        over = "entry filled"  # EL3
    elif mark > 0 and (mark - plan.stop) * _sign(p.side) <= 0:
        over = "stop reached before the entry filled"  # E4
    elif st.entry_deadline_ms and now >= st.entry_deadline_ms:
        over = "entry expired"  # E5
    elif st.finish_entry:
        over = "entry ended early"  # E14
    if over is not None:
        pulled = [await runner._cancel_clip(c) for c in live]
        if not all(pulled):
            return
        if over != "entry filled":
            st.reason = over
        closed = max((c.closed_at or 0 for c in clips), default=0)
        await runner._entry_over(now, filled, avg, closed_at=closed or st.created_at)
        return
    if runner._entry_vanished_ms and now - runner._entry_vanished_ms < MISSING_GRACE_MS:
        st.reason = "entry waits for a rung's fills"  # E13
        return
    if not pending:
        st.reason = f"{len(live)} rungs resting"
        return
    view = runner._chase_view()
    if view is None:
        st.reason = "entry waits: book not synced"
        return
    # EL1: a rung that would cross waits. Nearest the market goes on first.
    ready = sort_by_closeness(
        [r for r in pending if is_passive(side=p.side, price=r.price, bid=view.bid, ask=view.ask)],
        p.side,
    )
    # EL4: from the algo rate budget, leaving room for the stop.
    room = budget.tx_room("algo") - RUNG_TX_RESERVE
    placed = 0
    for r in ready[: max(0, room)]:
        try:
            refused = await runner._rest_entry(r.price, r.qty, now)
        except Exception as e:
            if isinstance(e, BudgetRefused) or is_blocked(e):
                runner._backoff_until = now + RATE_LIMIT_COOLDOWN_MS
                break
            raise
        if refused is None:
            placed += 1
        elif refused == "min":
            # Under the venue minimum: the rung is as full as it gets.
            runner._gave_up.add(f"rung {fmt_decimal(r.price)}")
    resting = len(live) + placed
    waiting = len(pending) - placed
    st.reason = (
        f"{resting} rungs resting, {waiting} waiting" if waiting else f"{resting} rungs resting"
    )


def _pending_rungs(
    runner: PlannerRunner, rungs: tuple[Rung, ...], clips: list[Clip], half: Decimal
) -> list[Rung]:
    """EL1: rungs with nothing resting and something left to fill, at what is left."""
    ctx, _ = venue.market_context(runner._exec(), runner._state.market_index)
    out: list[Rung] = []
    for r in rungs:
        if f"rung {fmt_decimal(r.price)}" in runner._gave_up:
            continue
        mine = [c for c in clips if c.price == r.price]
        if any(c.status == "live" for c in mine):
            continue
        # A filled rung is not refilled.
        if any(c.status == "filled" for c in mine):
            continue
        got = sum((min(c.filled, c.qty) for c in mine), ZERO)
        left = round_qty(r.qty - got, ctx.qty_step)
        if left <= half or left < ctx.min_qty:
            continue
        out.append(dataclasses.replace(r, qty=left))
    return out


async def _track_entry(runner: PlannerRunner, now: int, prices: list[Decimal]) -> None:
    """E9: follow the best price, and fire the entry when the price comes back."""
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    if st.entry_deadline_ms and now >= st.entry_deadline_ms:
        await runner._cancel_all()
        runner._end("entry expired before it fired")  # E5, E6
        return
    if st.finish_entry:
        await runner._cancel_all()
        runner._end("entry ended before it fired")  # E14, E6
        return
    f = entry_follow(p, runner._tick())
    sign = _sign(p.side)
    point = st.trails.get("entry", Point())
    for px in prices:
        if (px - plan.stop) * sign <= 0:
            st.trails["entry"] = point
            await runner._cancel_all()
            runner._end("stop reached before the entry fired")  # E4
            return
        point = engine.follow(f, point, px)
        if point.active and point.trigger is not None and engine.crossed(f, point.trigger, px):
            st.trails["entry"] = point
            await runner._fire_entry(px)
            return
    st.trails["entry"] = point
    st.reason = "entry following" if point.active else "entry waits for its Activation"


async def _fire_entry(runner: PlannerRunner, px: Decimal) -> None:
    """E9 and P2: size from the price it fires at, check S1 again, send it at market."""
    st = runner._state
    p, plan = st.params, st.plan
    assert p is not None and plan is not None
    ctx, _ = venue.market_context(runner._exec(), st.market_index)
    try:
        size = plan_size(p, ctx, entry=px, stop=plan.stop)
        st.plan = price_plan(
            side=p.side,
            entry=px,
            stop=plan.stop,
            size=size,
            targets=p.targets,
            ctx=ctx,
            risk_pct=p.risk_pct,
            stop_steps=p.stop_steps,
            trail_stop=p.trail_stop,
        )
        check_notional(size, px, settings.max_order_notional)
    except (PlanRefused, ValueError) as e:
        await runner._cancel_all()
        runner._end(f"entry did not fire: {e}")
        return
    await runner._send_entry()
    st.reason = f"entry fired at {fmt_decimal(px)}"
