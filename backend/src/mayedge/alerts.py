"""Alerts, the funding strip and the Activity board.

The rules are docs/alert-rules.md; rule ids are in comments.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mayedge.alert_log import AlertLog
from mayedge.alert_stats import HourBase, LevelBook, MinuteBook
from mayedge.config import settings
from mayedge.lighter.models import Candle, MarketMeta, to_float

logger = logging.getLogger(__name__)

_RING = 500
_SNAPSHOT_MAX = 400
_MINUTES_PER_DAY = 1440
_STALE_S = 90.0
NOTABLE = 2
URGENT = 3
# One row for a move shared by the board. The symbol opens BTC.
BROAD_INDEX = -1
BROAD_SYMBOL = "BTC"
SPIKE_KINDS = frozenset({"move", "volume", "oi"})
# R4: states that go on firing once they start.
STATE_KINDS = frozenset({"liqs", "board", "near_liq"})
# R4: a state that keeps firing raises another row at half again its largest size.
_ESCALATE = 1.5
# R7: this close to the day's high or low counts as at it.
_AT_EXTREME_BPS = 2.0
# How many times the hour's biggest a minute can be said to be.
_MULTIPLE_CAP = 99.0
_PREMIUM_FLOOR_PCT = 0.05


@dataclass
class AlertSettings:
    min_24h_usd: float = 1_000_000.0
    max_spread_bps: float = 40.0
    spike_window_min: int = 60
    spike_price_x: float = 2.0
    spike_volume_x: float = 3.0
    spike_oi_x: float = 2.0
    spike_min_move_pct: float = 0.25
    spike_min_volume_usd: float = 50_000.0
    spike_min_oi_usd: float = 250_000.0
    spike_min_oi_pct: float = 0.3
    liq_oi_bps: float = 20.0
    liq_min_usd: float = 100_000.0
    liq_window_s: float = 120.0
    board_move_pct: float = 0.3
    board_min_movers: int = 10
    board_agree: float = 0.8
    board_median_pct: float = 0.5
    held_liq_distance_pct: float = 10.0
    funding_sigma: float = 3.0
    funding_sigma_floor: float = 0.002
    funding_retention_days: int = 30
    merge_s: float = 120.0
    quiet_s: float = 180.0
    max_new_per_min: int = 6
    log_retention_days: int = 90
    range_floor_pct: float = 3.0
    bars_1m: int = 240
    min_bars: int = 30
    level_window_min: int = 1440
    level_min_samples: int = 30
    horizon_min: int = 15
    retention_days: int = 30


def _f(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def thresholds_from_dict(data: dict[str, Any] | None) -> AlertSettings:
    d = data or {}
    base = AlertSettings()
    liquidity = d.get("liquidity") or {}
    spike = d.get("spike") or {}
    liqs = d.get("liquidations") or {}
    board = d.get("board") or {}
    held = d.get("held") or {}
    funding = d.get("funding") or {}
    rows = d.get("rows") or {}
    activity = d.get("activity") or {}
    baseline = d.get("baseline") or {}
    outcomes = d.get("outcomes") or {}
    return AlertSettings(
        min_24h_usd=_f(liquidity.get("min_24h_usd"), base.min_24h_usd),
        max_spread_bps=_f(liquidity.get("max_spread_bps"), base.max_spread_bps),
        spike_window_min=int(_f(spike.get("window_min"), base.spike_window_min)),
        spike_price_x=_f(spike.get("price_x"), base.spike_price_x),
        spike_volume_x=_f(spike.get("volume_x"), base.spike_volume_x),
        spike_oi_x=_f(spike.get("oi_x"), base.spike_oi_x),
        spike_min_move_pct=_f(spike.get("min_move_pct"), base.spike_min_move_pct),
        spike_min_volume_usd=_f(spike.get("min_volume_usd"), base.spike_min_volume_usd),
        spike_min_oi_usd=_f(spike.get("min_oi_usd"), base.spike_min_oi_usd),
        spike_min_oi_pct=_f(spike.get("min_oi_pct"), base.spike_min_oi_pct),
        liq_oi_bps=_f(liqs.get("oi_bps"), base.liq_oi_bps),
        liq_min_usd=_f(liqs.get("min_usd"), base.liq_min_usd),
        liq_window_s=_f(liqs.get("window_s"), base.liq_window_s),
        board_move_pct=_f(board.get("move_pct"), base.board_move_pct),
        board_min_movers=int(_f(board.get("min_movers"), base.board_min_movers)),
        board_agree=_f(board.get("agree"), base.board_agree),
        board_median_pct=_f(board.get("median_pct"), base.board_median_pct),
        held_liq_distance_pct=_f(held.get("liq_distance_pct"), base.held_liq_distance_pct),
        funding_sigma=_f(funding.get("sigma"), base.funding_sigma),
        funding_sigma_floor=_f(funding.get("sigma_floor"), base.funding_sigma_floor),
        funding_retention_days=int(_f(funding.get("retention_days"), base.funding_retention_days)),
        merge_s=_f(rows.get("merge_s"), base.merge_s),
        quiet_s=_f(rows.get("quiet_s"), base.quiet_s),
        max_new_per_min=int(_f(rows.get("max_new_per_min"), base.max_new_per_min)),
        log_retention_days=int(_f(rows.get("log_retention_days"), base.log_retention_days)),
        range_floor_pct=_f(activity.get("range_floor_pct"), base.range_floor_pct),
        bars_1m=int(_f(baseline.get("bars_1m"), base.bars_1m)),
        min_bars=int(_f(baseline.get("min_bars"), base.min_bars)),
        level_window_min=int(_f(baseline.get("level_window_min"), base.level_window_min)),
        level_min_samples=int(_f(baseline.get("level_min_samples"), base.level_min_samples)),
        horizon_min=int(_f(outcomes.get("horizon_min"), base.horizon_min)),
        retention_days=int(_f(outcomes.get("retention_days"), base.retention_days)),
    )


def resolve_alerts_config_path() -> Path:
    return Path(settings.alerts_config)


def load_thresholds(path: Path | None = None) -> AlertSettings:
    p = path or resolve_alerts_config_path()
    if not p.is_file():
        logger.warning("alerts yaml missing at %s; using defaults", p)
        return AlertSettings()
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError("root must be a mapping")
        thr = thresholds_from_dict(data)
        logger.info("loaded alert thresholds from %s", p)
        return thr
    except Exception:
        logger.exception("failed to parse %s; using defaults", p)
        return AlertSettings()


@dataclass
class MarketSnapshot:
    ts: float
    mark: float
    last: float
    index: float
    mid: float
    bid: float
    ask: float
    oi: float
    vol_quote: float
    funding: float
    premium: float
    day_high: float = 0.0
    day_low: float = 0.0


@dataclass(frozen=True)
class Held:
    """What the operator has on a market. No side means a working order and no Position."""

    side: str = ""
    liquidation_price: float = 0.0


@dataclass
class Fact:
    """One thing a row states. A rule that fired has a size; what the tape showed has none."""

    kind: str
    direction: str
    value: float
    unit: str
    window: str = ""
    size: float | None = None
    detail: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "kind": self.kind,
            "direction": self.direction,
            "value": self.value,
            "unit": self.unit,
        }
        if self.window:
            row["window"] = self.window
        if self.size is not None:
            row["size"] = round(self.size, 2)
        for key, value in self.detail.items():
            row[key] = round(value, 4)
        return row


@dataclass
class AlertEvent:
    id: str
    ts: int
    symbol: str
    market_index: int
    rule: str
    severity: int
    direction: str
    size: float
    price: float
    facts: list[dict[str, Any]]
    held: str
    started_at: int
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "symbol": self.symbol,
            "market_index": self.market_index,
            "rule": self.rule,
            "severity": self.severity,
            "direction": self.direction,
            "size": round(self.size, 2),
            "price": self.price,
            "facts": self.facts,
            "held": self.held,
            "started_at": self.started_at,
            "note": self.note,
        }


def _pct_change(now: float, prev: float) -> float | None:
    if prev <= 0 or now <= 0:
        return None
    return (now - prev) / prev * 100.0


def _spread_bps(bid: float, ask: float, mid: float) -> float | None:
    if bid <= 0 or ask <= 0 or mid <= 0 or ask < bid:
        return None
    return (ask - bid) / mid * 10_000.0


def _direction(delta: float) -> str:
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _multiple(value: float, biggest: float) -> float:
    """How many times the hour's biggest minute this one is. An empty hour reads as the cap."""
    if biggest <= 0:
        return _MULTIPLE_CAP
    return min(value / biggest, _MULTIPLE_CAP)


def _liq_event_ts_s(row: dict[str, Any], *, now: float) -> float:
    raw = row.get("timestamp", row.get("ts"))
    try:
        ts = int(raw or 0)
    except (TypeError, ValueError):
        ts = 0
    if ts <= 0:
        return now
    if ts > 1e16:
        ts //= 1_000_000
    elif ts > 1e14:
        ts //= 1000
    if ts < 1e12:
        return float(ts)
    return ts / 1000.0


def _usd(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return f"${a / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"${a / 1_000:.0f}k"
    return f"${a:.0f}"


def _hour(fact: Fact) -> str:
    multiple = fact.detail.get("multiple")
    return "" if multiple is None else f" · {multiple:.1f}× hour max"


def describe(fact: Fact) -> str:
    """The fact in desk shorthand. No label says what it means."""
    v = fact.value
    if fact.kind == "move":
        text = f"{v:+.2f}% 1m"
        if fact.size is not None:
            text += _hour(fact)
        excess = fact.detail.get("excess")
        if excess is not None:
            text += f" · {excess:+.2f}% past the board"
        return text
    if fact.kind == "volume":
        return f"Vol {_usd(v)} 1m{_hour(fact)}"
    if fact.kind == "oi":
        return f"OI {v:+.2f}% 1m{_hour(fact)}"
    if fact.kind == "liqs":
        side = "longs" if fact.direction == "down" else "shorts"
        return f"Liqs {_usd(v)} {side} · {fact.detail.get('bps', 0.0):.0f} bps of OI"
    if fact.kind == "board":
        return f"Board {v:+.2f}% · {fact.window} {fact.direction}"
    if fact.kind == "near_liq":
        return f"{v:.1f}% from liquidation"
    if fact.kind == "day_high":
        return "day high"
    if fact.kind == "day_low":
        return "day low"
    if fact.kind == "funding":
        return f"funding {v:+.4f}%/h"
    return fact.kind


@dataclass
class _Row:
    id: str
    market_index: int
    symbol: str
    started_s: float
    price: float
    rules: dict[str, Fact]
    context: dict[str, Fact]
    held: str

    def headline(self) -> Fact:
        return max(self.rules.values(), key=lambda f: f.size or 0.0)

    def size(self) -> float:
        return self.headline().size or 0.0

    def severity(self) -> int:
        """R3."""
        spikes = sum(1 for kind in self.rules if kind in SPIKE_KINDS)
        if spikes >= 2 or self.held or any(kind in STATE_KINDS for kind in self.rules):
            return URGENT
        return NOTABLE

    def direction(self) -> str:
        """The largest rule that points somewhere. Volume alone points nowhere."""
        for fact in sorted(self.rules.values(), key=lambda f: -(f.size or 0.0)):
            if fact.direction in ("up", "down"):
                return fact.direction
        return "flat"

    def signature(self) -> tuple[float, str, int, int]:
        return (round(self.size(), 1), self.headline().kind, len(self.rules), self.severity())

    def take(self, fired: Iterable[Fact], context: Iterable[Fact]) -> None:
        """Each rule kept at its largest. The tape is shown only where no rule already says it."""
        for fact in fired:
            prev = self.rules.get(fact.kind)
            if prev is None or (fact.size or 0.0) > (prev.size or 0.0):
                self.rules[fact.kind] = fact
            self.context.pop(fact.kind, None)
        for fact in context:
            if fact.kind in self.rules:
                continue
            prev = self.context.get(fact.kind)
            if prev is None or abs(fact.value) > abs(prev.value):
                self.context[fact.kind] = fact


class RowBook:
    """Which fired rules are news, and which row they belong on."""

    def __init__(self, cfg: AlertSettings) -> None:
        self._cfg = cfg
        self._rows: dict[int, _Row] = {}
        self._standing: dict[tuple[int, str], tuple[float, float]] = {}
        self._new_row_times: deque[float] = deque()

    def ingest(
        self,
        market_index: int,
        symbol: str,
        fired: list[Fact],
        context: list[Fact],
        now: float,
        *,
        price: float,
        held: str = "",
    ) -> AlertEvent | None:
        row = self._rows.get(market_index)
        # R2: a row takes updates for a while, then it is final.
        if row is not None and now - row.started_s >= self._cfg.merge_s:
            row = None
        news = [fact for fact in fired if self._is_news(market_index, fact, row, now)]
        if not news:
            return None

        if row is not None:
            before = row.signature()
            row.take(news, context)
            row.held = held or row.held
            if row.signature() == before:
                return None
            return self._event(row, now)

        if not self._cap_has_room(now):
            return None
        self._new_row_times.append(now)
        row = _Row(
            id=f"alert-{market_index}-{int(now)}",
            market_index=market_index,
            symbol=symbol,
            started_s=now,
            price=price,
            rules={},
            context={},
            held=held,
        )
        row.take(news, context)
        self._rows[market_index] = row
        return self._event(row, now)

    def _is_news(self, market_index: int, fact: Fact, row: _Row | None, now: float) -> bool:
        """K7 for a spike: always. R4 for a state: when it starts, and when it grows by half."""
        if fact.kind not in STATE_KINDS:
            return True
        key = (market_index, fact.kind)
        size = fact.size or 0.0
        standing = self._standing.get(key)
        if standing is None or now - standing[1] >= self._cfg.quiet_s:
            self._standing[key] = (size, now)
            return True
        largest, _last = standing
        if row is not None and fact.kind in row.rules:
            self._standing[key] = (max(largest, size), now)
            return True
        if size >= largest * _ESCALATE:
            self._standing[key] = (size, now)
            return True
        self._standing[key] = (largest, now)
        return False

    def _cap_has_room(self, now: float) -> bool:
        """R6."""
        while self._new_row_times and now - self._new_row_times[0] > 60.0:
            self._new_row_times.popleft()
        return len(self._new_row_times) < self._cfg.max_new_per_min

    def _event(self, row: _Row, now: float) -> AlertEvent:
        rules = sorted(row.rules.values(), key=lambda f: -(f.size or 0.0))
        facts = [*rules, *row.context.values()]
        return AlertEvent(
            id=row.id,
            ts=int(now * 1000),
            symbol=row.symbol,
            market_index=row.market_index,
            rule=rules[0].kind,
            severity=row.severity(),
            direction=row.direction(),
            size=row.size(),
            price=row.price,
            facts=[f.as_dict() for f in facts],
            held=row.held,
            started_at=int(row.started_s * 1000),
            note=" · ".join(describe(f) for f in facts),
        )


@dataclass(frozen=True)
class Broad:
    """B2: the side most movers share, when enough of them share it."""

    direction: str
    move_5m: float
    move_1m: float
    same: int
    movers: int
    liquid: int


_KNOB_ATTR = {
    "spike.price_x": "spike_price_x",
    "spike.min_move_pct": "spike_min_move_pct",
    "spike.volume_x": "spike_volume_x",
    "spike.min_volume_usd": "spike_min_volume_usd",
    "spike.oi_x": "spike_oi_x",
    "spike.min_oi_usd": "spike_min_oi_usd",
    "spike.min_oi_pct": "spike_min_oi_pct",
    "liquidations.min_usd": "liq_min_usd",
    "liquidations.oi_bps": "liq_oi_bps",
    "held.liq_distance_pct": "held_liq_distance_pct",
    "board.median_pct": "board_median_pct",
}


class AlertDetector:
    """Spikes and states that raise rows, the funding strip, and the Activity board."""

    def __init__(
        self,
        broadcast: Callable[[dict[str, Any]], None],
        thresholds: AlertSettings | None = None,
        log: AlertLog | None = None,
        held: Callable[[], Mapping[int, Held]] | None = None,
    ) -> None:
        self._broadcast = broadcast
        self._thr = thresholds if thresholds is not None else load_thresholds()
        self._held_fn = held
        self._held: tuple[float, Mapping[int, Held]] = (0.0, {})
        self._ring: list[dict[str, Any]] = []
        self._snapshots: dict[int, deque[MarketSnapshot]] = {}
        self._liq_window: dict[int, deque[tuple[float, float, str, str]]] = {}
        self._pending: list[AlertEvent] = []
        self._minute = MinuteBook(max_bars=self._thr.bars_1m, min_bars=self._thr.min_bars)
        self._level = LevelBook(
            window_min=self._thr.level_window_min,
            min_samples=self._thr.level_min_samples,
        )
        self._rows = RowBook(self._thr)
        self._log = log or AlertLog(
            horizon_min=self._thr.horizon_min,
            retention_days=self._thr.retention_days,
            log_retention_days=self._thr.log_retention_days,
        )
        self._symbols: dict[int, str] = {}
        self._broad_cache: tuple[float, Broad | None] | None = None

    @property
    def settings(self) -> AlertSettings:
        return self._thr

    def recent(self) -> list[dict[str, Any]]:
        return list(self._ring)

    def stats(self, *, hours: int, by: str = "rule") -> dict[str, Any]:
        """S5. `by=rule` keeps the 24h panel's rows."""
        since = int((time.time() - hours * 3600) * 1000)
        return {"hours": hours, "by": by, "rules": self._log.stats(since_ms=since, by=by)}

    def whatif(self, *, rule: str, knob: str, value: float, days: int) -> dict[str, Any]:
        """S7. A looser knob is reported and not replayed."""
        since = int((time.time() - days * 86_400) * 1000)
        current = float(getattr(self._thr, _KNOB_ATTR[knob])) if knob in _KNOB_ATTR else 0.0
        out = self._log.whatif(rule=rule, knob=knob, value=value, since_ms=since, current=current)
        section, key = knob.split(".", 1)
        out["days"] = days
        out["yaml"] = f"{section}:\n  {key}: {value:g}"
        return out

    def knob_settings(self) -> dict[str, Any]:
        from mayedge.alert_log import KNOBS

        knobs: dict[str, float] = {}
        by_rule: dict[str, list[str]] = {}
        for name, (kind, _field, _tighter) in KNOBS.items():
            knobs[name] = float(getattr(self._thr, _KNOB_ATTR[name]))
            by_rule.setdefault(kind, []).append(name)
        return {"knobs": knobs, "by_rule": by_rule}

    def opened(self, row_id: str) -> bool:
        """S3."""
        return self._log.opened(row_id, now_ms=int(time.time() * 1000))

    def minute_book(self) -> MinuteBook:
        return self._minute

    def liquid(self, market_index: int) -> bool:
        """G2, on this market's latest stats."""
        series = self._snapshots.get(market_index)
        return bool(series) and self._liquidity_ok(series[-1])

    def seed_minute_bars(self, market_index: int, bars: list[Candle]) -> None:
        self._minute.seed(market_index, bars)
        self._measure(market_index, time.time())

    def seed_levels(
        self, name: str, by_market: Mapping[int, Iterable[tuple[int, float]]]
    ) -> None:
        """K6, F3: stored minutes of funding or open interest, from before this run."""
        for market_index, samples in by_market.items():
            self._level.seed(market_index, name, samples)

    def on_minute_bars(self, market_index: int, bars: list[Candle]) -> None:
        self._minute.observe(market_index, bars)
        self._measure(market_index, time.time())

    def on_market_stats(self, meta: MarketMeta) -> None:
        # G1.
        if not meta.is_perp:
            return
        mi = meta.market_index
        self._symbols[mi] = meta.symbol
        snap = self._snapshot_from_meta(meta)
        if snap is None or not self._record_snapshot(mi, snap):
            return
        self._level.observe(mi, "premium", ts=snap.ts, value=self._premium(snap))
        self._level.observe(mi, "funding", ts=snap.ts, value=snap.funding)
        if snap.oi > 0:
            self._level.observe(mi, "oi", ts=snap.ts, value=snap.oi)
        self._evaluate(mi, snap.ts)

    def on_liquidations(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        now = time.time()
        touched: set[int] = set()
        for i, row in enumerate(items):
            try:
                mi = int(row.get("market_index") or 0)
            except (TypeError, ValueError):
                continue
            if mi <= 0:
                continue
            usd = to_float(row.get("usd_amount"))
            if usd <= 0:
                usd = to_float(row.get("price")) * to_float(row.get("size"))
            side = str(row.get("side") or "")
            key = str(row.get("trade_id") or "") or f"anon:{i}"
            ts = _liq_event_ts_s(row, now=now)
            kept = [item for item in self._liq_window.get(mi, ()) if item[3] != key]
            kept.append((ts, usd, side, key))
            kept.sort(key=lambda item: item[0])
            self._liq_window[mi] = deque(kept)
            touched.add(mi)
        for mi in touched:
            if self._snapshots.get(mi):
                self._evaluate(mi, now)
        self.flush()

    def flush(self) -> None:
        now = time.time()
        fact = self._board_fact(now)
        ev = self._rows.ingest(
            BROAD_INDEX, BROAD_SYMBOL, [fact] if fact else [], [], now, price=0.0
        )
        if ev:
            self._record(ev, now)
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        self._emit(pending)

    def funding_extremes(self) -> list[dict[str, Any]]:
        """F2: every liquid or Held market whose funding is extreme now, furthest first."""
        now = time.time()
        held = self._held_book(now)
        rows: list[dict[str, Any]] = []
        for mi, series in self._snapshots.items():
            snap = series[-1]
            if now - snap.ts > _STALE_S or not (mi in held or self._liquidity_ok(snap)):
                continue
            z = self._funding_z(mi, snap)
            if z is None:
                continue
            rows.append(
                {
                    "market_index": mi,
                    "symbol": self._symbols.get(mi, f"M{mi}"),
                    "funding": snap.funding,
                    "z": round(z, 2),
                    "held": mi in held,
                }
            )
        rows.sort(key=lambda row: (-abs(float(row["z"])), str(row["symbol"])))
        return rows

    def activity(self) -> list[dict[str, Any]]:
        """A1, A2: every liquid perp and what its tape shows now."""
        now = time.time()
        held = self._held_book(now)
        rows: list[dict[str, Any]] = []
        for mi, series in self._snapshots.items():
            snap = series[-1]
            if now - snap.ts > _STALE_S or not self._liquidity_ok(snap):
                continue
            day = self._day_range(snap)
            base = self._find_baseline(series, 300.0)
            move = _pct_change(snap.last, base.last) if base else None
            metrics = self._minute.metrics(mi, volume_floor=snap.vol_quote / _MINUTES_PER_DAY)
            oi_pct = _pct_change(snap.oi, base.oi) if base else None
            premium = self._premium(snap)
            rows.append(
                {
                    "market_index": mi,
                    "symbol": self._symbols.get(mi, f"M{mi}"),
                    "move_5m": move,
                    "share": None if move is None else abs(move) / day,
                    "day_range": day,
                    "vol_x": metrics.rvol_5m if metrics else None,
                    "vol_usd_5m": metrics.vol_quote_5m if metrics else None,
                    "oi_5m": oi_pct,
                    "oi_usd_5m": None if oi_pct is None or base is None else snap.oi - base.oi,
                    "funding": snap.funding,
                    "funding_z": self._level.z(
                        mi, "funding", snap.funding, floor=self._thr.funding_sigma_floor
                    ),
                    "premium": premium,
                    "premium_z": self._level.z(mi, "premium", premium, floor=_PREMIUM_FLOOR_PCT),
                    "held": mi in held,
                }
            )
        rows.sort(key=lambda row: str(row["symbol"]))
        return rows

    def _snapshot_from_meta(self, meta: MarketMeta) -> MarketSnapshot | None:
        mark = to_float(meta.mark_price)
        last = to_float(meta.last_trade_price)
        if mark <= 0 and last <= 0:
            return None
        return MarketSnapshot(
            ts=time.time(),
            mark=mark or last,
            last=last or mark,
            index=to_float(meta.index_price),
            mid=to_float(meta.mid_price),
            bid=to_float(meta.best_bid_price),
            ask=to_float(meta.best_ask_price),
            oi=to_float(meta.open_interest),
            vol_quote=to_float(meta.volume_24h),
            funding=to_float(meta.funding_rate),
            premium=to_float(meta.premium),
            day_high=to_float(meta.daily_price_high),
            day_low=to_float(meta.daily_price_low),
        )

    def _record_snapshot(self, market_index: int, snap: MarketSnapshot) -> bool:
        series = self._snapshots.setdefault(market_index, deque(maxlen=_SNAPSHOT_MAX))
        if series and snap.ts - series[-1].ts < 0.9:
            series[-1] = snap
            return False
        series.append(snap)
        return True

    def _find_baseline(self, series: deque[MarketSnapshot], age_s: float) -> MarketSnapshot | None:
        """The newest print at least ``age_s`` old, if one is near that age."""
        if not series:
            return None
        newest = series[-1]
        target = newest.ts - age_s
        best: MarketSnapshot | None = None
        for snap in reversed(series):
            if snap.ts <= target:
                best = snap
                break
        if best is None:
            return None
        if newest.ts - best.ts < age_s * 0.8:
            return None
        return best

    def _liquidity_ok(self, snap: MarketSnapshot) -> bool:
        if snap.vol_quote < self._thr.min_24h_usd:
            return False
        spread = _spread_bps(snap.bid, snap.ask, snap.mid or snap.last)
        return spread is None or spread <= self._thr.max_spread_bps

    def _held_book(self, now: float) -> Mapping[int, Held]:
        """H1. Asked for at most once a second."""
        if self._held_fn is None:
            return self._held[1]
        if abs(now - self._held[0]) >= 1.0:
            try:
                self._held = (now, self._held_fn())
            except Exception:
                logger.exception("held markets lookup failed")
                self._held = (now, {})
        return self._held[1]

    def _premium(self, snap: MarketSnapshot) -> float:
        if snap.premium == 0 and snap.index > 0 and snap.mark > 0:
            return (snap.mark - snap.index) / snap.index * 100.0
        return snap.premium

    def _day_range(self, snap: MarketSnapshot) -> float:
        """A2: the Day range in percent, never under the floor."""
        pct = 0.0
        if snap.day_low > 0 and snap.day_high >= snap.day_low:
            pct = (snap.day_high - snap.day_low) / snap.day_low * 100.0
        return max(pct, self._thr.range_floor_pct)

    def _funding_z(self, market_index: int, snap: MarketSnapshot) -> float | None:
        """F1: the sigmas, when funding is extreme. None when it is not."""
        z = self._level.z(
            market_index, "funding", snap.funding, floor=self._thr.funding_sigma_floor
        )
        if z is None or abs(z) < self._thr.funding_sigma:
            return None
        return z

    def _evaluate(self, market_index: int, now: float) -> None:
        series = self._snapshots[market_index]
        snap = series[-1]
        symbol = self._symbols.get(market_index, f"M{market_index}")
        held = self._held_book(now).get(market_index)
        facts: list[Fact] = []
        # G2, G3.
        if held is not None or self._liquidity_ok(snap):
            hour = self._minute.hour(market_index, now=now, window_min=self._thr.spike_window_min)
            for fact in (
                self._move_fact(series, snap, hour, now),
                self._volume_fact(hour),
                self._oi_fact(market_index, series, snap, now),
                self._liq_fact(market_index, snap, now),
                self._near_liq_fact(snap, held),
            ):
                if fact is not None:
                    facts.append(fact)
        fired = [f for f in facts if f.size is not None]
        if not fired:
            return
        # R5, R7, R8.
        context = [f for f in facts if f.size is None]
        context.extend(self._tags(market_index, snap))
        label = "" if held is None else (held.side or "order")
        ev = self._rows.ingest(
            market_index, symbol, fired, context, now, price=snap.last, held=label
        )
        if ev:
            self._record(ev, now)

    def _move_fact(
        self,
        series: deque[MarketSnapshot],
        snap: MarketSnapshot,
        hour: HourBase | None,
        now: float,
    ) -> Fact | None:
        """K2, K5. The 1m move, as a spike when it is one and as plain tape when it is not."""
        base = self._find_baseline(series, 60.0)
        pct = _pct_change(snap.last, base.last) if base else None
        if pct is None:
            return None
        fact = Fact("move", _direction(pct), pct, "pct", window="1m")
        fact.detail["share"] = abs(pct) / self._day_range(snap)
        judged = pct
        # K5: with the board, only the part beyond it counts.
        broad = self._broad(now)
        if (
            broad is not None
            and _direction(pct) == broad.direction
            and _direction(broad.move_1m) == broad.direction
        ):
            judged = pct - broad.move_1m
            if _direction(judged) != broad.direction:
                return fact
            fact.detail["excess"] = judged
        if hour is None:
            return fact
        fact.detail["multiple"] = _multiple(abs(judged), hour.max_move_pct)
        threshold = max(self._thr.spike_price_x * hour.max_move_pct, self._thr.spike_min_move_pct)
        if abs(judged) >= threshold:
            fact.size = abs(judged) / threshold
        return fact

    def _volume_fact(self, hour: HourBase | None) -> Fact | None:
        """K3. Shown once it is the hour's biggest minute, a spike at three times that."""
        if hour is None:
            return None
        usd = hour.forming_volume_usd
        if usd < self._thr.spike_min_volume_usd or usd < hour.max_volume_usd:
            return None
        fact = Fact("volume", "flat", usd, "usd", window="1m")
        fact.detail["multiple"] = _multiple(usd, hour.max_volume_usd)
        threshold = max(
            self._thr.spike_volume_x * hour.max_volume_usd, self._thr.spike_min_volume_usd
        )
        if usd >= threshold:
            fact.size = usd / threshold
        return fact

    def _oi_fact(
        self,
        market_index: int,
        series: deque[MarketSnapshot],
        snap: MarketSnapshot,
        now: float,
    ) -> Fact | None:
        """K4. Shown once it is the hour's biggest change, a spike at twice that."""
        base = self._find_baseline(series, 60.0)
        if base is None or base.oi <= 0 or snap.oi <= 0:
            return None
        delta = snap.oi - base.oi
        pct = delta / base.oi * 100.0
        if abs(delta) < self._thr.spike_min_oi_usd or abs(pct) < self._thr.spike_min_oi_pct:
            return None
        changes = self._level.changes(
            market_index, "oi", now=now, window_min=self._thr.spike_window_min
        )
        if changes is None:
            return None
        biggest = max(changes, default=0.0)
        if abs(delta) < biggest:
            return None
        fact = Fact("oi", _direction(delta), pct, "pct", window="1m")
        fact.detail["multiple"] = _multiple(abs(delta), biggest)
        fact.detail["usd"] = delta
        threshold = max(self._thr.spike_oi_x * biggest, self._thr.spike_min_oi_usd)
        if abs(delta) >= threshold:
            fact.size = abs(delta) / threshold
        return fact

    def _liq_fact(self, market_index: int, snap: MarketSnapshot, now: float) -> Fact | None:
        """L1, L2."""
        window = self._liq_window.get(market_index)
        if not window:
            return None
        cutoff = now - self._thr.liq_window_s
        while window and window[0][0] < cutoff:
            window.popleft()
        total = sum(item[1] for item in window)
        if total < self._thr.liq_min_usd or snap.oi <= 0:
            return None
        bps = total / snap.oi * 10_000.0
        if bps < self._thr.liq_oi_bps:
            return None
        sells = sum(1 for item in window if item[2] == "sell")
        return Fact(
            "liqs",
            "down" if sells >= len(window) / 2 else "up",
            total,
            "usd",
            size=bps / self._thr.liq_oi_bps,
            detail={"bps": bps},
        )

    def _near_liq_fact(self, snap: MarketSnapshot, held: Held | None) -> Fact | None:
        """H2."""
        if held is None or not held.side or held.liquidation_price <= 0 or snap.mark <= 0:
            return None
        distance = abs(snap.mark - held.liquidation_price) / snap.mark * 100.0
        within = self._thr.held_liq_distance_pct
        if distance > within:
            return None
        return Fact(
            "near_liq",
            "down" if held.liquidation_price < snap.mark else "up",
            distance,
            "pct",
            size=within / max(distance, 0.1),
            detail={"liquidation_price": held.liquidation_price},
        )

    def _tags(self, market_index: int, snap: MarketSnapshot) -> list[Fact]:
        """R7, R8."""
        out: list[Fact] = []
        near = _AT_EXTREME_BPS / 10_000.0
        if snap.day_high > 0 and snap.last >= snap.day_high * (1 - near):
            out.append(Fact("day_high", "up", snap.day_high, "px"))
        elif snap.day_low > 0 and snap.last <= snap.day_low * (1 + near):
            out.append(Fact("day_low", "down", snap.day_low, "px"))
        z = self._funding_z(market_index, snap)
        if z is not None:
            out.append(Fact("funding", _direction(z), snap.funding, "pct_hr", detail={"z": z}))
        return out

    def _broad(self, now: float) -> Broad | None:
        """B1, B2. Worked out once a second."""
        hit = self._broad_cache
        if hit is not None and abs(now - hit[0]) < 1.0:
            return hit[1]
        moves: dict[int, float] = {}
        for mi, series in self._snapshots.items():
            snap = series[-1]
            if now - snap.ts > _STALE_S or not self._liquidity_ok(snap):
                continue
            base = self._find_baseline(series, 300.0)
            pct = _pct_change(snap.last, base.last) if base else None
            if pct is not None:
                moves[mi] = pct
        cut = self._thr.board_move_pct
        up = [mi for mi, pct in moves.items() if pct >= cut]
        down = [mi for mi, pct in moves.items() if pct <= -cut]
        side = up if len(up) >= len(down) else down
        movers = len(up) + len(down)
        broad: Broad | None = None
        if len(side) >= self._thr.board_min_movers and len(side) / movers >= self._thr.board_agree:
            minute: list[float] = []
            for mi in side:
                series = self._snapshots[mi]
                base = self._find_baseline(series, 60.0)
                pct = _pct_change(series[-1].last, base.last) if base else None
                if pct is not None:
                    minute.append(pct)
            broad = Broad(
                direction="up" if side is up else "down",
                move_5m=statistics.median(moves[mi] for mi in side),
                move_1m=statistics.median(minute) if minute else 0.0,
                same=len(side),
                movers=movers,
                liquid=len(moves),
            )
        self._broad_cache = (now, broad)
        return broad

    def _board_fact(self, now: float) -> Fact | None:
        """B3."""
        broad = self._broad(now)
        if broad is None or abs(broad.move_5m) < self._thr.board_median_pct:
            return None
        return Fact(
            "board",
            broad.direction,
            broad.move_5m,
            "pct",
            window=f"{broad.same}/{broad.movers}",
            size=abs(broad.move_5m) / self._thr.board_median_pct,
            detail={"liquid": float(broad.liquid)},
        )

    def _record(self, ev: AlertEvent, now: float) -> None:
        """S1, then queue the row for the panel."""
        try:
            self._log.write(ev.as_dict(), entry_bar=int(now // 60) * 60)
        except Exception:
            logger.exception("alert row not written id=%s", ev.id)
        self._pending.append(ev)

    def _measure(self, market_index: int, now: float) -> None:
        """S2."""
        if not self._log.awaiting(market_index):
            return
        try:
            self._log.resolve(market_index, self._minute.bars(market_index), now=now)
        except Exception:
            logger.exception("alert rows not measured market=%s", market_index)

    def _emit(self, events: list[AlertEvent]) -> None:
        public = [e.as_dict() for e in events]
        by_id: dict[str, dict[str, Any]] = {}
        for row in public + self._ring:
            rid = str(row.get("id") or "")
            if not rid:
                continue
            prev = by_id.get(rid)
            if prev is None or int(row.get("ts") or 0) >= int(prev.get("ts") or 0):
                by_id[rid] = row
        self._ring = sorted(
            by_id.values(),
            key=lambda r: int(r.get("ts") or 0),
            reverse=True,
        )[:_RING]
        self._broadcast({"type": "alerts", "events": public})
