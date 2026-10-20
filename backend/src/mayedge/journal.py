"""Rebuild Round trips from stored fills. No I/O. Rules: docs/journal-rules.md."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ZERO = Decimal("0")
_MS = 10**12

GroupBy = Literal["day", "market", "algo", "none"]

_FAMILIES = {
    "PL": "planner",
    "CH": "chase",
    "CG": "grid",
    "LD": "ladder",
    "TW": "twap",
    "TR": "trail",
}


@dataclass(frozen=True)
class Fill:
    trade_id: str
    market_index: int
    symbol: str
    side: str
    is_maker: bool
    price: Decimal
    size: Decimal
    usd: Decimal
    fee: Decimal
    pnl: Decimal
    kind: str
    ts: int


@dataclass(frozen=True)
class FundingPayment:
    market_index: int
    ts: int
    amount: Decimal


@dataclass(frozen=True)
class FillPart:
    trade_id: str
    ts: int
    side: str
    price: Decimal
    size: Decimal
    fee: Decimal
    pnl: Decimal
    usd: Decimal
    is_maker: bool
    closing: bool


@dataclass(frozen=True)
class RoundTrip:
    trip_key: str
    market_index: int
    symbol: str
    side: str
    open_ts: int
    close_ts: int | None
    size: Decimal
    avg_in: Decimal | None
    avg_out: Decimal | None
    pnl: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal
    algo: str
    algo_id: str | None
    r: Decimal | None
    partial: bool
    partial_reason: str | None
    open: bool
    upnl: Decimal | None
    fills: tuple[FillPart, ...]


@dataclass(frozen=True)
class CurvePoint:
    ts: int
    net: Decimal


@dataclass(frozen=True)
class Summary:
    key: str
    count: int
    wins: int
    losses: int
    win_rate: Decimal | None
    gross_pnl: Decimal
    fees: Decimal
    funding: Decimal
    net: Decimal
    avg_win: Decimal | None
    avg_loss: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None
    maker_share: Decimal | None
    avg_r: Decimal | None
    total_r: Decimal | None
    curve: tuple[CurvePoint, ...]
    max_drawdown: Decimal | None


def family_of(algo_id: str) -> str:
    prefix = algo_id.split("-", 1)[0]
    return _FAMILIES.get(prefix, prefix.lower() or "manual")


def seconds_of(ts: int) -> int:
    return ts // 1000 if ts > _MS else ts


def round_trips(
    fills: list[Fill],
    funding: list[FundingPayment],
    algo_links: dict[str, str],
    planner_risk: dict[str, tuple[Decimal, Decimal]],
    *,
    oldest_ts: int | None = None,
    upnl: dict[int, Decimal] | None = None,
) -> list[RoundTrip]:
    """Flat to flat, per Market. `planner_risk` maps a Planner id to (entry, stop)."""
    by_market: dict[int, list[Fill]] = defaultdict(list)
    for fill in fills:
        if fill.size > 0:
            by_market[fill.market_index].append(fill)
    fund_by_market: dict[int, list[FundingPayment]] = defaultdict(list)
    for row in funding:
        fund_by_market[row.market_index].append(row)

    trips: list[RoundTrip] = []
    for market_index, rows in by_market.items():
        rows.sort(key=lambda fill: (fill.ts, _trade_order(fill.trade_id)))
        built = _replay(rows, algo_links, oldest_ts=oldest_ts)
        live = None if upnl is None else upnl.get(market_index)
        trips.extend(
            _with_funding(built, fund_by_market.get(market_index, []), live, planner_risk)
        )
    trips.sort(key=lambda trip: (trip.open_ts, trip.market_index, trip.trip_key))
    return trips


def summary(trips: list[RoundTrip], group_by: GroupBy) -> list[Summary]:
    counted = [trip for trip in trips if not trip.partial and not trip.open and trip.close_ts is not None]
    groups: dict[str, list[RoundTrip]] = defaultdict(list)
    if group_by == "none":
        groups["all"] = counted
    else:
        for trip in counted:
            groups[_group_key(trip, group_by)].append(trip)
    out = [_summarize(key, rows, with_curve=group_by == "none") for key, rows in groups.items()]
    out.sort(key=lambda row: row.key)
    return out


def _trade_order(trade_id: str) -> tuple[int, str]:
    try:
        return (0, f"{int(trade_id):020d}")
    except ValueError:
        return (1, trade_id)


def _replay(
    rows: list[Fill],
    algo_links: dict[str, str],
    *,
    oldest_ts: int | None,
) -> list[RoundTrip]:
    pos = ZERO
    opening: list[FillPart] = []
    closing: list[FillPart] = []
    trips: list[RoundTrip] = []

    def emit(partial: bool, reason: str | None, *, still_open: bool) -> None:
        nonlocal opening, closing
        if not opening and not closing:
            return
        trips.append(
            _trip(
                opening,
                closing,
                rows[0].market_index,
                rows[0].symbol,
                algo_links,
                partial=partial,
                reason=reason,
                still_open=still_open,
                oldest_ts=oldest_ts,
            )
        )
        opening = []
        closing = []

    for fill in rows:
        delta = fill.size if fill.side == "buy" else -fill.size
        if pos == 0 and fill.pnl != 0:
            closing = [_part(fill, fill.size, fill.fee, fill.pnl, fill.usd, closing=True)]
            emit(True, "history starts mid-position", still_open=False)
            continue
        if pos == 0 or (pos > 0) == (delta > 0):
            opening.append(_part(fill, fill.size, fill.fee, ZERO, fill.usd, closing=False))
            pos += delta
            continue
        close_qty = min(abs(delta), abs(pos))
        open_qty = abs(delta) - close_qty
        fee_close = fill.fee * close_qty / fill.size
        usd_close = fill.usd * close_qty / fill.size
        closing.append(_part(fill, close_qty, fee_close, fill.pnl, usd_close, closing=True))
        pos += delta
        # Flat, or the remainder opened the other side. A partial close stays open.
        flipped = pos != 0 and (pos > 0) == (delta > 0)
        if pos == 0 or flipped:
            emit(False, None, still_open=False)
            if open_qty > 0:
                opening.append(
                    _part(
                        fill,
                        open_qty,
                        fill.fee - fee_close,
                        ZERO,
                        fill.usd - usd_close,
                        closing=False,
                    )
                )
    if opening or closing:
        emit(False, None, still_open=True)
    return trips


def _part(
    fill: Fill, size: Decimal, fee: Decimal, pnl: Decimal, usd: Decimal, *, closing: bool
) -> FillPart:
    return FillPart(
        trade_id=fill.trade_id,
        ts=fill.ts,
        side=fill.side,
        price=fill.price,
        size=size,
        fee=fee,
        pnl=pnl,
        usd=usd,
        is_maker=fill.is_maker,
        closing=closing,
    )


def _trip(
    opening: list[FillPart],
    closing: list[FillPart],
    market_index: int,
    symbol: str,
    algo_links: dict[str, str],
    *,
    partial: bool,
    reason: str | None,
    still_open: bool,
    oldest_ts: int | None,
) -> RoundTrip:
    parts = tuple(opening + closing)
    first = parts[0]
    if oldest_ts is not None and first.ts < oldest_ts:
        partial = True
        reason = reason or "opened before the stored history"
    side = _side_of(opening, closing)
    size = sum((part.size for part in opening), ZERO) or sum((part.size for part in closing), ZERO)
    pnl = sum((part.pnl for part in parts), ZERO)
    fees = sum((part.fee for part in parts), ZERO)
    algo_id, algo = _algo(opening, algo_links)
    net = pnl - fees
    close_ts = closing[-1].ts if closing and not still_open else None
    return RoundTrip(
        trip_key=f"{market_index}:{first.trade_id}",
        market_index=market_index,
        symbol=symbol,
        side=side,
        open_ts=first.ts,
        close_ts=close_ts,
        size=size,
        avg_in=_avg(opening),
        avg_out=_avg(closing),
        pnl=pnl,
        fees=fees,
        funding=ZERO,
        net=net,
        algo=algo,
        algo_id=algo_id,
        r=None,
        partial=partial,
        partial_reason=reason if partial else None,
        open=still_open,
        upnl=None,
        fills=parts,
    )


def _side_of(opening: list[FillPart], closing: list[FillPart]) -> str:
    if opening:
        return "long" if opening[0].side == "buy" else "short"
    return "long" if closing[0].side == "sell" else "short"


def _avg(parts: list[FillPart]) -> Decimal | None:
    size = sum((part.size for part in parts), ZERO)
    if size == 0:
        return None
    notional = sum((part.price * part.size for part in parts), ZERO)
    return notional / size


def _algo(opening: list[FillPart], algo_links: dict[str, str]) -> tuple[str | None, str]:
    """The algo with the most opening size. A tie keeps the one that opened first."""
    sizes: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for part in opening:
        algo_id = algo_links.get(part.trade_id)
        if algo_id:
            sizes[algo_id] += part.size
    if not sizes:
        return None, "manual"
    best = ZERO
    chosen = ""
    for part in opening:
        algo_id = algo_links.get(part.trade_id)
        if algo_id and sizes[algo_id] > best:
            best = sizes[algo_id]
            chosen = algo_id
    return chosen, family_of(chosen)


def _risk(
    algo: str, algo_id: str | None, size: Decimal, planner_risk: dict[str, tuple[Decimal, Decimal]]
) -> Decimal | None:
    if algo != "planner" or not algo_id or algo_id not in planner_risk:
        return None
    entry, stop = planner_risk[algo_id]
    risk = abs(entry - stop) * size
    return risk if risk > 0 else None


def _with_funding(
    trips: list[RoundTrip],
    rows: list[FundingPayment],
    live: Decimal | None,
    planner_risk: dict[str, tuple[Decimal, Decimal]],
) -> list[RoundTrip]:
    if not trips:
        return []
    ordered = sorted(rows, key=lambda row: row.ts)
    out: list[RoundTrip] = []
    for index, trip in enumerate(trips):
        end = trip.close_ts
        prev_close = trips[index - 1].close_ts if index else None
        # A print on the shared flip timestamp stays with the trip that closed.
        start_after = prev_close is not None and prev_close == trip.open_ts
        amount = ZERO
        for row in ordered:
            if start_after:
                if row.ts <= trip.open_ts:
                    continue
            elif row.ts < trip.open_ts:
                continue
            if end is not None and row.ts > end:
                continue
            amount += row.amount
        net = trip.pnl - trip.fees + amount
        risk = None if trip.partial else _risk(trip.algo, trip.algo_id, trip.size, planner_risk)
        upnl = live if trip.open else None
        out.append(
            RoundTrip(
                trip_key=trip.trip_key,
                market_index=trip.market_index,
                symbol=trip.symbol,
                side=trip.side,
                open_ts=trip.open_ts,
                close_ts=trip.close_ts,
                size=trip.size,
                avg_in=trip.avg_in,
                avg_out=trip.avg_out,
                pnl=trip.pnl,
                fees=trip.fees,
                funding=amount,
                net=net,
                algo=trip.algo,
                algo_id=trip.algo_id,
                r=(net / risk) if risk else None,
                partial=trip.partial,
                partial_reason=trip.partial_reason,
                open=trip.open,
                upnl=upnl,
                fills=trip.fills,
            )
        )
    return out


def _group_key(trip: RoundTrip, group_by: GroupBy) -> str:
    if group_by == "market":
        return trip.symbol
    if group_by == "algo":
        return trip.algo
    assert trip.close_ts is not None
    day = time.gmtime(seconds_of(trip.close_ts))
    return f"{day.tm_year:04d}-{day.tm_mon:02d}-{day.tm_mday:02d}"


def _summarize(key: str, trips: list[RoundTrip], *, with_curve: bool) -> Summary:
    wins = [trip for trip in trips if trip.net > 0]
    losses = [trip for trip in trips if trip.net < 0]
    count = len(trips)
    gross = sum((trip.pnl for trip in trips), ZERO)
    fees = sum((trip.fees for trip in trips), ZERO)
    funding = sum((trip.funding for trip in trips), ZERO)
    net = sum((trip.net for trip in trips), ZERO)
    win_net = sum((trip.net for trip in wins), ZERO)
    loss_net = sum((trip.net for trip in losses), ZERO)
    decided = len(wins) + len(losses)
    rs = [trip.r for trip in trips if trip.r is not None]
    usd = ZERO
    maker = ZERO
    for trip in trips:
        for part in trip.fills:
            usd += part.usd
            if part.is_maker:
                maker += part.usd
    curve: tuple[CurvePoint, ...] = ()
    drawdown: Decimal | None = None
    if with_curve:
        curve, drawdown = _curve(trips)
    return Summary(
        key=key,
        count=count,
        wins=len(wins),
        losses=len(losses),
        win_rate=(Decimal(len(wins)) / Decimal(decided)) if decided else None,
        gross_pnl=gross,
        fees=fees,
        funding=funding,
        net=net,
        avg_win=(win_net / len(wins)) if wins else None,
        avg_loss=(loss_net / len(losses)) if losses else None,
        profit_factor=(win_net / abs(loss_net)) if losses and win_net != 0 else (None if not losses else ZERO),
        expectancy=(net / count) if count else None,
        largest_win=max((trip.net for trip in wins), default=None),
        largest_loss=min((trip.net for trip in losses), default=None),
        maker_share=(maker / usd) if usd else None,
        avg_r=(sum(rs, ZERO) / len(rs)) if rs else None,
        total_r=sum(rs, ZERO) if rs else None,
        curve=curve,
        max_drawdown=drawdown,
    )


def _curve(trips: list[RoundTrip]) -> tuple[tuple[CurvePoint, ...], Decimal | None]:
    ordered = sorted(trips, key=lambda trip: (trip.close_ts or 0, trip.trip_key))
    if not ordered:
        return (), None
    points: list[CurvePoint] = []
    running = ZERO
    peak = ZERO
    worst = ZERO
    for trip in ordered:
        running += trip.net
        points.append(CurvePoint(ts=trip.close_ts or 0, net=running))
        if running > peak:
            peak = running
        drop = peak - running
        if drop > worst:
            worst = drop
    return tuple(points), worst
