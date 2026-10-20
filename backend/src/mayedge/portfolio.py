"""The Portfolio now: value, Day change and Flows per Holding kind. No I/O.

Rules: docs/portfolio-rules.md. The totals are the venue's own `pnl` buckets (V1–V4);
holding detail only adds quantities to them (N6).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any, Literal

Kind = Literal["perps", "spot", "llp", "staking"]
KINDS: tuple[Kind, ...] = ("perps", "spot", "llp", "staking")

ZERO = Decimal("0")
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
MAX_OPEN_BACK_MS = 30 * DAY_MS
MISMATCH_USD = Decimal("1")

LLP_POOL = 281474976710654
STAKING_POOL = 281474976624800

# Kind → (value and PnL field, inflow field, outflow field) in a pnl bucket (V3).
FIELDS: dict[Kind, tuple[str, str, str]] = {
    "perps": ("trade_pnl", "inflow", "outflow"),
    "spot": ("trade_spot_pnl", "spot_inflow", "spot_outflow"),
    "llp": ("pool_pnl", "pool_inflow", "pool_outflow"),
    "staking": ("staking_pnl", "staking_inflow", "staking_outflow"),
}

_QUOTE = frozenset({"USDC", "USD"})


class OpenRefused(ValueError):
    """N1: a Day open in the future, or too far back."""


def _dec(raw: Any) -> Decimal:
    if raw is None or raw == "":
        return ZERO
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return ZERO


def to_ms(ts: Any) -> int:
    """V5, A4: the venue answers seconds; a value above 10^12 is already ms."""
    n = int(_dec(ts))
    return n if n > 10**12 else n * 1000


@dataclass(frozen=True)
class Bucket:
    ts_ms: int
    fields: dict[str, Decimal]

    def get(self, name: str) -> Decimal:
        return self.fields.get(name, ZERO)


def buckets(rows: list[dict[str, Any]]) -> list[Bucket]:
    out = [
        Bucket(to_ms(row.get("timestamp")), {k: _dec(v) for k, v in row.items() if k != "timestamp"})
        for row in rows
        if isinstance(row, dict)
    ]
    out.sort(key=lambda b: b.ts_ms)
    return out


def day_open(open_ms: int | None, now_ms: int) -> int:
    """N1: the caller's open, down to the hour. None is today's UTC midnight."""
    if open_ms is None:
        return now_ms - now_ms % DAY_MS
    if open_ms > now_ms or now_ms - open_ms > MAX_OPEN_BACK_MS:
        raise OpenRefused("The Day open must be within the last 30 days")
    return open_ms - open_ms % HOUR_MS


def _at(series: list[Bucket], ts_ms: int) -> Bucket | None:
    """N2: the bucket stamped at ts, or the latest one before it."""
    found: Bucket | None = None
    for b in series:
        if b.ts_ms > ts_ms:
            break
        found = b
    return found


def _flow(b: Bucket | None, kind: Kind) -> Decimal:
    if b is None:
        return ZERO
    _field, inflow, outflow = FIELDS[kind]
    return b.get(inflow) - b.get(outflow)


@dataclass(frozen=True)
class KindNow:
    value: Decimal
    value_at_open: Decimal
    change: Decimal
    flows: Decimal


@dataclass(frozen=True)
class Mismatch:
    kind: Kind
    drift: Decimal


def kinds_now(pnl: list[Bucket], values: list[Bucket], open_ms: int) -> dict[Kind, KindNow]:
    """N2, N3: per kind from the two series (default and ignore_transfers)."""
    out: dict[Kind, KindNow] = {}
    pnl_now = pnl[-1] if pnl else None
    pnl_open = _at(pnl, open_ms)
    value_now = values[-1] if values else None
    value_open = _at(values, open_ms)
    for kind in KINDS:
        name = FIELDS[kind][0]
        now_pnl = pnl_now.get(name) if pnl_now else ZERO
        open_pnl = pnl_open.get(name) if pnl_open else ZERO
        out[kind] = KindNow(
            value=value_now.get(name) if value_now else ZERO,
            value_at_open=value_open.get(name) if value_open else ZERO,
            change=now_pnl - open_pnl,
            flows=_flow(pnl_now, kind) - _flow(pnl_open, kind),
        )
    return out


def change_pct(change: Decimal, value_at_open: Decimal, flows: Decimal) -> Decimal | None:
    """N4: today's change over what was at work today."""
    base = value_at_open + flows
    if base <= 0:
        return None
    return change / base * 100


def mismatches(pnl: list[Bucket], values: list[Bucket]) -> list[Mismatch]:
    """N5, V3 on the latest bucket of each series."""
    if not pnl or not values:
        return []
    out: list[Mismatch] = []
    for kind in KINDS:
        name = FIELDS[kind][0]
        drift = values[-1].get(name) - pnl[-1].get(name) - _flow(pnl[-1], kind)
        if abs(drift) > MISMATCH_USD:
            out.append(Mismatch(kind, drift))
    return out


@dataclass(frozen=True)
class PoolRow:
    pool: int
    kind: Kind
    shares: Decimal
    units: Decimal
    unit: str
    value: Decimal | None
    apy: Decimal | None
    principal: Decimal | None


def pool_row(share: dict[str, Any], pool_account: dict[str, Any] | None, lit_price: Decimal) -> PoolRow:
    """N6, P4, P5: what one pool share holds."""
    index = int(_dec(share.get("public_pool_index")))
    shares = _dec(share.get("shares_amount"))
    principal = _dec(share.get("principal_amount")) or None
    info = (pool_account or {}).get("pool_info") or {}
    total_shares = _dec(info.get("total_shares"))
    apy = _dec(info.get("annual_percentage_yield")) if info.get("annual_percentage_yield") is not None else None
    if index == STAKING_POOL:
        lit = ZERO
        for asset in (pool_account or {}).get("assets") or []:
            if str(asset.get("symbol")).upper() == "LIT":
                lit = _dec(asset.get("balance"))
        units = shares * lit / total_shares if total_shares > 0 else ZERO
        value = units * lit_price if lit_price > 0 else None
        return PoolRow(index, "staking", shares, units, "LIT", value, apy, principal)
    tav = _dec((pool_account or {}).get("total_asset_value"))
    value = shares * tav / total_shares if total_shares > 0 else None
    return PoolRow(index, "llp", shares, value or ZERO, "USD", value, apy, principal)


@dataclass(frozen=True)
class SpotRow:
    symbol: str
    qty: Decimal
    price: Decimal
    value: Decimal
    upnl: Decimal | None


def spot_rows(assets: list[Any]) -> list[SpotRow]:
    """N6, A1: the desk's live asset rows, quote left out."""
    out: list[SpotRow] = []
    for asset in assets:
        get = asset.get if isinstance(asset, dict) else lambda k, a=asset: getattr(a, k, None)
        symbol = str(get("symbol") or "").upper()
        if not symbol or symbol in _QUOTE:
            continue
        upnl = get("unrealized_pnl")
        out.append(
            SpotRow(
                symbol=symbol,
                qty=_dec(get("balance")),
                price=_dec(get("index_price")),
                value=_dec(get("usd")),
                upnl=_dec(upnl) if upnl not in (None, "") else None,
            )
        )
    out.sort(key=lambda row: -row.value)
    return out


@dataclass(frozen=True)
class Unlock:
    asset_index: int
    amount: Decimal
    unlock_ms: int


def unlocks(account: dict[str, Any]) -> list[Unlock]:
    rows = [
        Unlock(int(_dec(u.get("asset_index"))), _dec(u.get("amount")), to_ms(u.get("unlock_timestamp")))
        for u in account.get("pending_unlocks") or []
        if isinstance(u, dict)
    ]
    rows.sort(key=lambda u: u.unlock_ms)
    return rows


@dataclass
class PortfolioNow:
    ts_ms: int
    open_ms: int
    kinds: dict[Kind, KindNow]
    mismatch: list[Mismatch]
    spot: list[SpotRow] = field(default_factory=list)
    pools: list[PoolRow] = field(default_factory=list)
    pending: list[Unlock] = field(default_factory=list)

    def total(self) -> KindNow:
        return KindNow(
            value=sum((k.value for k in self.kinds.values()), ZERO),
            value_at_open=sum((k.value_at_open for k in self.kinds.values()), ZERO),
            change=sum((k.change for k in self.kinds.values()), ZERO),
            flows=sum((k.flows for k in self.kinds.values()), ZERO),
        )

    def to_json(self) -> dict[str, Any]:
        def kind_json(k: KindNow) -> dict[str, Any]:
            pct = change_pct(k.change, k.value_at_open, k.flows)
            return {
                "value": _s(k.value),
                "value_at_open": _s(k.value_at_open),
                "change": _s(k.change),
                "change_pct": _s(pct),
                "flows": _s(k.flows),
            }

        return {
            "ts": self.ts_ms,
            "open": self.open_ms,
            "total": kind_json(self.total()),
            "kinds": {name: kind_json(k) for name, k in self.kinds.items()},
            "mismatch": [{"kind": m.kind, "drift": _s(m.drift)} for m in self.mismatch],
            "spot": [
                {"symbol": r.symbol, "qty": _s(r.qty), "price": _s(r.price), "value": _s(r.value), "upnl": _s(r.upnl)}
                for r in self.spot
            ],
            "pools": [
                {
                    "pool": r.pool,
                    "kind": r.kind,
                    "shares": _s(r.shares),
                    "units": _s(r.units),
                    "unit": r.unit,
                    "value": _s(r.value),
                    "apy": _s(r.apy),
                    "principal": _s(r.principal),
                }
                for r in self.pools
            ],
            "unlocks": [
                {"asset_index": u.asset_index, "amount": _s(u.amount), "unlock_ms": u.unlock_ms} for u in self.pending
            ],
        }


def _s(d: Decimal | None) -> str | None:
    if d is None:
        return None
    text = format(d.normalize(), "f")
    return "0" if text in ("-0", "") else text


def portfolio_now(
    *,
    now_ms: int,
    open_ms: int,
    pnl_rows: list[dict[str, Any]],
    value_rows: list[dict[str, Any]],
    account: dict[str, Any],
    pool_accounts: dict[int, dict[str, Any]],
    live_assets: list[Any],
    lit_price: Decimal,
) -> PortfolioNow:
    pnl, values = buckets(pnl_rows), buckets(value_rows)
    return PortfolioNow(
        ts_ms=now_ms,
        open_ms=open_ms,
        kinds=kinds_now(pnl, values, open_ms),
        mismatch=mismatches(pnl, values),
        spot=spot_rows(live_assets),
        pools=[
            pool_row(share, pool_accounts.get(int(_dec(share.get("public_pool_index")))), lit_price)
            for share in account.get("shares") or []
            if isinstance(share, dict)
        ],
        pending=unlocks(account),
    )


FLOW_MARKER_USD = Decimal("1")
HOURLY_HORIZON_MS = 90 * DAY_MS


def history(value_rows: list[dict[str, Any]], pnl_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """H4, H5: each kind's value at every stored bucket, and where Flows moved."""
    values = buckets(value_rows)
    points: list[dict[str, Any]] = []
    for b in values:
        row: dict[str, Any] = {"ts": b.ts_ms}
        total = ZERO
        for kind in KINDS:
            v = b.get(FIELDS[kind][0])
            row[kind] = _s(v)
            total += v
        row["total"] = _s(total)
        points.append(row)
    flows: list[dict[str, Any]] = []
    pnl = buckets(pnl_rows)
    for before, after in pairwise(pnl):
        for kind in KINDS:
            moved = _flow(after, kind) - _flow(before, kind)
            if abs(moved) > FLOW_MARKER_USD:
                flows.append({"ts": after.ts_ms, "kind": kind, "amount": _s(moved)})
    return {"points": points, "flows": flows}


def _local_midnights(since_ms: int, now_ms: int, tz_min: int) -> list[int]:
    """H6: local midnights from the one at or before since, to now. tz is UTC minus local, in minutes."""
    shift = tz_min * 60_000
    local = since_ms - shift
    first = local - local % DAY_MS + shift
    out = [first]
    while out[-1] + DAY_MS <= now_ms:
        out.append(out[-1] + DAY_MS)
    return out


def _day_label(start_ms: int, tz_min: int) -> str:
    day = time.gmtime((start_ms - tz_min * 60_000) / 1000)
    return f"{day.tm_year:04d}-{day.tm_mon:02d}-{day.tm_mday:02d}"


def days(
    hourly_pnl: list[dict[str, Any]],
    daily_pnl: list[dict[str, Any]],
    *,
    since_ms: int,
    now_ms: int,
    tz_min: int,
) -> list[dict[str, Any]]:
    """H6: Day change per kind for each day. Local days on hourly buckets; UTC days before them."""
    hourly, daily = buckets(hourly_pnl), buckets(daily_pnl)
    hourly_from = max(now_ms - HOURLY_HORIZON_MS, hourly[0].ts_ms if hourly else now_ms)
    out: list[dict[str, Any]] = []

    def row(label: str, start: int, utc: bool, open_b: Bucket | None, close_b: Bucket | None) -> None:
        if close_b is None:
            return
        kinds = {}
        total = ZERO
        for kind in KINDS:
            name = FIELDS[kind][0]
            change = close_b.get(name) - (open_b.get(name) if open_b else ZERO)
            kinds[kind] = _s(change)
            total += change
        out.append({"day": label, "start": start, "utc": utc, "kinds": kinds, "total": _s(total)})

    # UTC days before the hourly series begins.
    for open_b, close_b in pairwise(daily):
        if open_b.ts_ms < since_ms - DAY_MS or close_b.ts_ms > hourly_from:
            continue
        row(_day_label(open_b.ts_ms, 0), open_b.ts_ms, True, open_b, close_b)
    # Local days on the hourly series; the last one runs to the latest stored bucket.
    starts = [m for m in _local_midnights(max(since_ms, hourly_from), now_ms, tz_min) if m >= hourly_from]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else now_ms
        row(_day_label(start, tz_min), start, False, _at(hourly, start), _at(hourly, end))
    return out
