"""Setups: positioning and range facts on closed hours and days (docs/setup-rules.md, ADR 0026).

Pure: `find_setups` reads what it is given and returns rows. Nothing here reads the venue,
the database, or sends anything.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from mayedge.alert_stats import completed_extremes
from mayedge.lighter.models import Candle

_DAY_S = 86_400
# G3.
BOARD_MAX = 20


@dataclass(frozen=True)
class SetupSettings:
    oi_pct: float = 5.0
    oi_over_price: float = 3.0
    funding_hours: int = 72
    funding_agree: float = 0.9
    funding_x: float = 3.0
    board_pct: float = 1.0
    gap_pct: float = 5.0
    coil_days: int = 3
    coil_ratio: float = 0.5
    coil_near_pct: float = 2.0
    flush_bps: float = 50.0
    flush_oi_pct: float = 3.0


# X2: the 30 days before the window, and how many of them it needs.
FUNDING_BASE_DAYS = 30
FUNDING_BASE_MIN_DAYS = 7
# X4: the 30 completed days before the coil.
COIL_BASE_DAYS = 30


def _f(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def setup_settings_from_dict(data: dict[str, Any] | None) -> SetupSettings:
    raw = (data or {}).get("setups") or {}
    if not isinstance(raw, dict):
        raw = {}
    base = SetupSettings()
    return SetupSettings(
        oi_pct=_f(raw.get("oi_pct"), base.oi_pct),
        oi_over_price=_f(raw.get("oi_over_price"), base.oi_over_price),
        funding_hours=int(_f(raw.get("funding_hours"), base.funding_hours)),
        funding_agree=_f(raw.get("funding_agree"), base.funding_agree),
        funding_x=_f(raw.get("funding_x"), base.funding_x),
        board_pct=_f(raw.get("board_pct"), base.board_pct),
        gap_pct=_f(raw.get("gap_pct"), base.gap_pct),
        coil_days=int(_f(raw.get("coil_days"), base.coil_days)),
        coil_ratio=_f(raw.get("coil_ratio"), base.coil_ratio),
        coil_near_pct=_f(raw.get("coil_near_pct"), base.coil_near_pct),
        flush_bps=_f(raw.get("flush_bps"), base.flush_bps),
        flush_oi_pct=_f(raw.get("flush_oi_pct"), base.flush_oi_pct),
    )


@dataclass
class MarketRead:
    """One liquid perp, as the board reads it."""

    market_index: int
    symbol: str
    last: float
    change_24h: float | None = None
    oi_now: float | None = None
    oi_24h_ago: float | None = None
    oi_4h_ago: float | None = None
    funding_z: float | None = None
    # X2. Settled prints, oldest first: the window, and the 30 days before it.
    funding_window: list[float] = field(default_factory=list)
    funding_before: list[float] = field(default_factory=list)
    funding_window_complete: bool = False
    # X4, X5. Completed UTC daily bars, oldest first.
    daily: list[Candle] = field(default_factory=list)
    # X6. The last 4 hours.
    liq_long_usd: float = 0.0
    liq_short_usd: float = 0.0


@dataclass(frozen=True)
class Setup:
    kind: str
    market_index: int
    symbol: str
    direction: str
    size: float
    price: float
    note: str
    facts: dict[str, Any]


def _pct(now: float | None, then: float | None) -> float | None:
    if now is None or then is None or then <= 0:
        return None
    return (now - then) / then * 100.0


def _signed(v: float, digits: int = 1) -> str:
    text = f"{abs(v):.{digits}f}"
    if float(text) == 0:
        return text
    return ("−" if v < 0 else "+") + text


def _px(v: float) -> str:
    text = f"{v:,.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _usd(v: float) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"${a / 1e3:.0f}k"
    return f"${a:.0f}"


def oi_without_price(m: MarketRead, cfg: SetupSettings) -> Setup | None:
    """X1."""
    oi = _pct(m.oi_now, m.oi_24h_ago)
    price = m.change_24h
    if oi is None or price is None or abs(oi) < cfg.oi_pct:
        return None
    if abs(price) > abs(oi) / cfg.oi_over_price:
        return None
    note = f"OI {_signed(oi)}% 24h · price {_signed(price)}% 24h"
    if m.funding_z is not None:
        note += f" · funding {_signed(m.funding_z)}σ"
    facts = {"oi_pct": round(oi, 2), "price_pct": round(price, 2), "funding_z": m.funding_z}
    return Setup(
        "oi_price", m.market_index, m.symbol, "flat", abs(oi) / cfg.oi_pct, m.last, note, facts
    )


def funding_stretched(m: MarketRead, cfg: SetupSettings) -> Setup | None:
    """X2."""
    window = m.funding_window
    if not m.funding_window_complete or len(window) < cfg.funding_hours:
        return None
    if len(m.funding_before) < FUNDING_BASE_MIN_DAYS * 24:
        return None
    pos = sum(1 for r in window if r > 0)
    neg = sum(1 for r in window if r < 0)
    agree = max(pos, neg) / len(window)
    if agree < cfg.funding_agree:
        return None
    base = statistics.median(abs(r) for r in m.funding_before)
    mean = statistics.fmean(window)
    if base <= 0 or mean == 0:
        return None
    multiple = abs(mean) / base
    if multiple < cfg.funding_x:
        return None
    pays = "longs" if mean > 0 else "shorts"
    note = (
        f"funding {mean:+.4f}%/h over {len(window)}h · {agree * 100:.0f}% one sign · "
        f"{multiple:.1f}× its 30d median · {pays} pay"
    )
    facts = {"mean": mean, "agree": round(agree, 3), "multiple": round(multiple, 2), "pays": pays}
    return Setup(
        "funding", m.market_index, m.symbol, "flat", multiple / cfg.funding_x, m.last, note, facts
    )


def against_the_board(m: MarketRead, btc: float | None, cfg: SetupSettings) -> Setup | None:
    """X3. BTC itself is never against the board."""
    if btc is None or m.change_24h is None or m.symbol == "BTC":
        return None
    gap = m.change_24h - btc
    if btc <= -cfg.board_pct and gap >= cfg.gap_pct:
        direction = "up"
    elif btc >= cfg.board_pct and gap <= -cfg.gap_pct:
        direction = "down"
    else:
        return None
    note = f"{_signed(m.change_24h)}% 24h · BTC {_signed(btc)}%"
    facts = {"change_pct": m.change_24h, "btc_pct": btc, "gap": round(gap, 2)}
    return Setup(
        "board", m.market_index, m.symbol, direction, abs(gap) / cfg.gap_pct, m.last, note, facts
    )


def _range_pct(bar: Candle) -> float:
    return (bar.high - bar.low) / bar.low * 100.0 if bar.low > 0 else 0.0


def _completed(bars: list[Candle], now: float) -> list[Candle]:
    today = int(now) // _DAY_S * _DAY_S
    return sorted((b for b in bars if b.time < today and b.low > 0), key=lambda b: b.time)


def coiled_at_a_level(m: MarketRead, now: float, cfg: SetupSettings) -> Setup | None:
    """X4."""
    days = _completed(m.daily, now)
    if len(days) < cfg.coil_days + COIL_BASE_DAYS or m.last <= 0:
        return None
    recent = days[-cfg.coil_days :]
    base = days[-(cfg.coil_days + COIL_BASE_DAYS) : -cfg.coil_days]
    base_range = statistics.fmean(_range_pct(b) for b in base)
    if base_range <= 0:
        return None
    ratio = statistics.fmean(_range_pct(b) for b in recent) / base_range
    if ratio > cfg.coil_ratio:
        return None
    week = completed_extremes(m.daily, now=now, days=7)
    if week is None:
        return None
    high, low = week
    near: list[tuple[float, str, float]] = []
    for level, name in ((high, "week high"), (low, "week low")):
        distance = abs(m.last - level) / level * 100.0
        if distance <= cfg.coil_near_pct:
            near.append((distance, name, level))
    if not near:
        return None
    distance, name, level = min(near)
    note = f"range {ratio:.2f}× its 30d · {distance:.1f}% from {name} {_px(level)}"
    facts = {"ratio": round(ratio, 3), "level": level, "name": name, "distance": round(distance, 2)}
    return Setup(
        "coil",
        m.market_index,
        m.symbol,
        "flat",
        cfg.coil_ratio / max(ratio, 0.01),
        m.last,
        note,
        facts,
    )


def reclaim(m: MarketRead, now: float) -> Setup | None:
    """X5. Yesterday broke the week before it and closed back inside."""
    days = _completed(m.daily, now)
    if not days:
        return None
    today = int(now) // _DAY_S * _DAY_S
    yesterday = days[-1]
    if yesterday.time != today - _DAY_S:
        return None
    week = completed_extremes(days, now=float(yesterday.time), days=7)
    if week is None:
        return None
    high, low = week
    if yesterday.low < low < yesterday.close:
        note = f"under week low {_px(low)} to {_px(yesterday.low)}, closed {_px(yesterday.close)}"
        facts = {
            "level": low,
            "through": yesterday.low,
            "close": yesterday.close,
            "name": "week low",
        }
        return Setup("reclaim", m.market_index, m.symbol, "up", 1.0, m.last, note, facts)
    if yesterday.high > high > yesterday.close:
        note = f"over week high {_px(high)} to {_px(yesterday.high)}, closed {_px(yesterday.close)}"
        facts = {
            "level": high,
            "through": yesterday.high,
            "close": yesterday.close,
            "name": "week high",
        }
        return Setup("reclaim", m.market_index, m.symbol, "down", 1.0, m.last, note, facts)
    return None


def liquidation_flush(m: MarketRead, cfg: SetupSettings) -> Setup | None:
    """X6."""
    oi_change = _pct(m.oi_now, m.oi_4h_ago)
    if m.oi_4h_ago is None or m.oi_4h_ago <= 0 or oi_change is None:
        return None
    if oi_change > -cfg.flush_oi_pct:
        return None
    side, usd = ("longs", m.liq_long_usd)
    if m.liq_short_usd > m.liq_long_usd:
        side, usd = ("shorts", m.liq_short_usd)
    bps = usd / m.oi_4h_ago * 10_000
    if bps < cfg.flush_bps:
        return None
    note = f"{side} {_usd(usd)} liquidated in 4h · {bps:.0f} bps of OI · OI {_signed(oi_change)}%"
    facts = {"side": side, "usd": usd, "bps": round(bps, 1), "oi_pct": round(oi_change, 2)}
    return Setup(
        "flush", m.market_index, m.symbol, "flat", bps / cfg.flush_bps, m.last, note, facts
    )


def find_setups(
    reads: list[MarketRead], btc_change: float | None, now: float, cfg: SetupSettings
) -> list[Setup]:
    """Every Setup on every read market, the largest first, at most BOARD_MAX (G3)."""
    out: list[Setup] = []
    for m in reads:
        for found in (
            oi_without_price(m, cfg),
            funding_stretched(m, cfg),
            against_the_board(m, btc_change, cfg),
            coiled_at_a_level(m, now, cfg),
            reclaim(m, now),
            liquidation_flush(m, cfg),
        ):
            if found is not None:
                out.append(found)
    out.sort(key=lambda s: (-s.size, s.symbol, s.kind))
    return out[:BOARD_MAX]
