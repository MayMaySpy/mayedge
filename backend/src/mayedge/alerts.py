from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mayedge.config import settings
from mayedge.lighter.models import MarketMeta, to_float

logger = logging.getLogger(__name__)

_RING = 500
_SNAPSHOT_MAX = 1200  # ~20 min at 1 sample/s


@dataclass(frozen=True)
class SevPair:
    sev2: float
    sev3: float


@dataclass
class ExploitThresholds:
    cooldown_s: float = 90.0
    level_cooldown_s: float = 300.0
    min_severity: int = 2
    max_events_per_flush: int = 20
    warmup_s: float = 20.0
    oi_pct_1m: SevPair = field(default_factory=lambda: SevPair(8.0, 20.0))
    oi_pct_5m: SevPair = field(default_factory=lambda: SevPair(15.0, 35.0))
    price_pct_1m: SevPair = field(default_factory=lambda: SevPair(1.5, 4.0))
    price_pct_5m: SevPair = field(default_factory=lambda: SevPair(3.0, 8.0))
    vol_usd_1m: SevPair = field(default_factory=lambda: SevPair(750_000.0, 2_500_000.0))
    vol_usd_5m: SevPair = field(default_factory=lambda: SevPair(2_000_000.0, 8_000_000.0))
    spread_bps: SevPair = field(default_factory=lambda: SevPair(50.0, 150.0))
    premium_pct: SevPair = field(default_factory=lambda: SevPair(0.5, 1.2))
    disloc_bps: SevPair = field(default_factory=lambda: SevPair(50.0, 120.0))
    funding_hourly_pct: SevPair = field(default_factory=lambda: SevPair(0.20, 0.60))
    liq_count: SevPair = field(default_factory=lambda: SevPair(5.0, 12.0))
    liq_usd: SevPair = field(default_factory=lambda: SevPair(250_000.0, 1_000_000.0))
    liq_window_s: float = 120.0


_LEVEL_KINDS = frozenset({"spread", "premium", "dislocation", "funding"})


def _pair(raw: Any, default: SevPair) -> SevPair:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            a, b = float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return default
        if b < a:
            a, b = b, a
        return SevPair(a, b)
    return default


def _f(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def thresholds_from_dict(data: dict[str, Any] | None) -> ExploitThresholds:
    d = data or {}
    oi = d.get("oi") or {}
    price = d.get("price") or {}
    vol = d.get("volume") or {}
    spread = d.get("spread") or {}
    prem = d.get("premium") or {}
    disloc = d.get("dislocation") or {}
    funding = d.get("funding") or {}
    liq = d.get("liq_cluster") or {}
    base = ExploitThresholds()
    return ExploitThresholds(
        cooldown_s=_f(d.get("cooldown_s"), base.cooldown_s),
        level_cooldown_s=_f(d.get("level_cooldown_s"), base.level_cooldown_s),
        min_severity=max(1, min(3, int(_f(d.get("min_severity"), base.min_severity)))),
        max_events_per_flush=max(
            1, int(_f(d.get("max_events_per_flush"), base.max_events_per_flush))
        ),
        warmup_s=_f(d.get("warmup_s"), base.warmup_s),
        oi_pct_1m=_pair(oi.get("pct_1m"), base.oi_pct_1m),
        oi_pct_5m=_pair(oi.get("pct_5m"), base.oi_pct_5m),
        price_pct_1m=_pair(price.get("pct_1m"), base.price_pct_1m),
        price_pct_5m=_pair(price.get("pct_5m"), base.price_pct_5m),
        vol_usd_1m=_pair(vol.get("usd_1m"), base.vol_usd_1m),
        vol_usd_5m=_pair(vol.get("usd_5m"), base.vol_usd_5m),
        spread_bps=_pair(spread.get("bps"), base.spread_bps),
        premium_pct=_pair(prem.get("pct"), base.premium_pct),
        disloc_bps=_pair(disloc.get("bps"), base.disloc_bps),
        funding_hourly_pct=_pair(funding.get("hourly_pct"), base.funding_hourly_pct),
        liq_count=_pair(liq.get("count"), base.liq_count),
        liq_usd=_pair(liq.get("usd"), base.liq_usd),
        liq_window_s=_f(liq.get("window_s"), base.liq_window_s),
    )


def resolve_alerts_config_path() -> Path:
    """Editable thresholds live in backend/config/alerts.yaml (cwd-relative)."""
    return Path(settings.alerts_config)


def load_thresholds(path: Path | None = None) -> ExploitThresholds:
    p = path or resolve_alerts_config_path()
    if not p.is_file():
        logger.warning("alerts yaml missing at %s; using defaults", p)
        return ExploitThresholds()
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError("root must be a mapping")
        thr = thresholds_from_dict(data)
        logger.info("loaded alert thresholds from %s", p)
        return thr
    except Exception:
        logger.exception("failed to parse %s; using defaults", p)
        return ExploitThresholds()


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


@dataclass
class ExploitEvent:
    id: str
    ts: int
    symbol: str
    market_index: int
    kind: str
    severity: int
    direction: str
    value: float
    baseline: float | None
    unit: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "symbol": self.symbol,
            "market_index": self.market_index,
            "kind": self.kind,
            "severity": self.severity,
            "direction": self.direction,
            "value": self.value,
            "baseline": self.baseline,
            "unit": self.unit,
            "note": self.note,
        }


def _pct_change(now: float, prev: float) -> float | None:
    if prev <= 0 or now <= 0:
        return None
    return (now - prev) / prev * 100.0


def _bps_diff(a: float, b: float, ref: float) -> float | None:
    if ref <= 0 or a <= 0 or b <= 0:
        return None
    return abs(a - b) / ref * 10_000.0


def _spread_bps(bid: float, ask: float, mid: float) -> float | None:
    if bid <= 0 or ask <= 0 or mid <= 0 or ask < bid:
        return None
    return (ask - bid) / mid * 10_000.0


def _severity_from_thresholds(value: float, pair: SevPair) -> int:
    av = abs(value)
    if av >= pair.sev3:
        return 3
    if av >= pair.sev2:
        return 2
    return 1


def _direction_from_delta(delta: float) -> str:
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


class ExploitDetector:
    """Snapshot ring + threshold scanner for Lighter market inefficiencies."""

    def __init__(
        self,
        broadcast: Callable[[dict[str, Any]], None],
        thresholds: ExploitThresholds | None = None,
    ) -> None:
        self._broadcast = broadcast
        self._thr = thresholds if thresholds is not None else load_thresholds()
        self._ring: list[dict[str, Any]] = []
        self._snapshots: dict[int, deque[MarketSnapshot]] = {}
        self._seen_since: dict[int, float] = {}
        self._cooldown: dict[tuple[int, str], float] = {}
        self._liq_window: dict[int, deque[tuple[float, float, str]]] = {}
        self._pending: list[ExploitEvent] = []

    def recent(self) -> list[dict[str, Any]]:
        return list(self._ring)

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
        )

    def _record_snapshot(self, market_index: int, snap: MarketSnapshot) -> bool:
        series = self._snapshots.setdefault(market_index, deque(maxlen=_SNAPSHOT_MAX))
        self._seen_since.setdefault(market_index, snap.ts)
        if series and snap.ts - series[-1].ts < 0.9:
            series[-1] = snap
            return False
        series.append(snap)
        return True

    def _find_baseline(self, series: deque[MarketSnapshot], age_s: float) -> MarketSnapshot | None:
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

    def _cooldown_s(self, kind: str) -> float:
        if kind in _LEVEL_KINDS:
            return self._thr.level_cooldown_s
        return self._thr.cooldown_s

    def _cooldown_ok(self, market_index: int, kind: str) -> bool:
        key = (market_index, kind)
        last = self._cooldown.get(key, 0.0)
        return time.time() - last >= self._cooldown_s(kind)

    def _mark_cooldown(self, market_index: int, kind: str) -> None:
        self._cooldown[market_index, kind] = time.time()

    def _queue(self, events: list[ExploitEvent]) -> None:
        floor = self._thr.min_severity
        for ev in events:
            if ev.severity < floor:
                continue
            self._pending.append(ev)

    def flush(self) -> None:
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        pending.sort(key=lambda e: (e.severity, e.ts), reverse=True)
        cap = self._thr.max_events_per_flush
        if len(pending) > cap:
            pending = pending[:cap]
        self._emit(pending)

    def _emit(self, events: list[ExploitEvent]) -> None:
        if not events:
            return
        public = [e.as_dict() for e in events]
        merged = public + self._ring
        by_id: dict[str, dict[str, Any]] = {}
        for row in merged:
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

    def on_market_stats(self, meta: MarketMeta) -> None:
        if not meta.is_perp:
            return
        snap = self._snapshot_from_meta(meta)
        if snap is None:
            return
        if not self._record_snapshot(meta.market_index, snap):
            return
        self._queue(self._scan(meta, snap))

    def on_liquidations(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        now = time.time()
        by_market: dict[int, list[tuple[float, float, str]]] = {}
        for row in items:
            try:
                mi = int(row.get("market_index") or 0)
            except (TypeError, ValueError):
                continue
            if mi <= 0:
                continue
            usd = to_float(row.get("usd_amount"))
            if usd <= 0:
                px = to_float(row.get("price"))
                sz = to_float(row.get("size"))
                usd = px * sz
            side = str(row.get("side") or "")
            by_market.setdefault(mi, []).append((now, usd, side))

        out: list[ExploitEvent] = []
        window_s = self._thr.liq_window_s
        for mi, rows in by_market.items():
            window = self._liq_window.setdefault(mi, deque())
            for ts, usd, side in rows:
                window.append((ts, usd, side))
            cutoff = now - window_s
            while window and window[0][0] < cutoff:
                window.popleft()
            if not window:
                continue
            count = len(window)
            total_usd = sum(r[1] for r in window)
            sev = 0
            if count >= self._thr.liq_count.sev3 or total_usd >= self._thr.liq_usd.sev3:
                sev = 3
            elif count >= self._thr.liq_count.sev2 or total_usd >= self._thr.liq_usd.sev2:
                sev = 2
            else:
                continue
            if not self._cooldown_ok(mi, "liq_cluster"):
                continue
            symbol = f"M{mi}"
            for row in items:
                if int(row.get("market_index") or 0) == mi:
                    symbol = str(row.get("symbol") or symbol)
                    break
            sells = sum(1 for _, _, s in window if s == "sell")
            direction = "down" if sells >= count / 2 else "up"
            out.append(
                ExploitEvent(
                    id=str(uuid.uuid4()),
                    ts=int(now * 1000),
                    symbol=symbol,
                    market_index=mi,
                    kind="liq_cluster",
                    severity=sev,
                    direction=direction,
                    value=total_usd,
                    baseline=float(count),
                    unit="usd",
                    note=f"{count} liqs in {window_s:.0f}s",
                )
            )
            self._mark_cooldown(mi, "liq_cluster")
        self._queue(out)
        self.flush()

    def _warm(self, market_index: int, now: float) -> bool:
        first = self._seen_since.get(market_index)
        if first is None:
            return False
        return now - first >= self._thr.warmup_s

    def _scan(self, meta: MarketMeta, snap: MarketSnapshot) -> list[ExploitEvent]:
        series = self._snapshots.get(meta.market_index)
        if not series or len(series) < 2:
            return []
        out: list[ExploitEvent] = []
        mi = meta.market_index
        sym = meta.symbol
        warm = self._warm(mi, snap.ts)

        for age, label in ((60.0, "1m"), (300.0, "5m")):
            base = self._find_baseline(series, age)
            if base is None:
                continue

            if snap.oi > 0 and base.oi > 0:
                oi_pct = _pct_change(snap.oi, base.oi)
                if oi_pct is not None:
                    pair = self._thr.oi_pct_1m if age <= 60 else self._thr.oi_pct_5m
                    sev = _severity_from_thresholds(oi_pct, pair)
                    if sev >= 2 and self._cooldown_ok(mi, f"oi_{label}"):
                        out.append(
                            ExploitEvent(
                                id=str(uuid.uuid4()),
                                ts=int(snap.ts * 1000),
                                symbol=sym,
                                market_index=mi,
                                kind="oi",
                                severity=sev,
                                direction=_direction_from_delta(oi_pct),
                                value=oi_pct,
                                baseline=base.oi,
                                unit="pct",
                                note=f"OI {label} Δ{oi_pct:+.1f}%",
                            )
                        )
                        self._mark_cooldown(mi, f"oi_{label}")

            if snap.vol_quote >= base.vol_quote:
                vol_delta = snap.vol_quote - base.vol_quote
                pair = self._thr.vol_usd_1m if age <= 60 else self._thr.vol_usd_5m
                sev = _severity_from_thresholds(vol_delta, pair)
                if sev >= 2 and self._cooldown_ok(mi, f"volume_{label}"):
                    out.append(
                        ExploitEvent(
                            id=str(uuid.uuid4()),
                            ts=int(snap.ts * 1000),
                            symbol=sym,
                            market_index=mi,
                            kind="volume",
                            severity=sev,
                            direction="up",
                            value=vol_delta,
                            baseline=base.vol_quote,
                            unit="usd",
                            note=f"Vol burst {label} +${vol_delta:,.0f}",
                        )
                    )
                    self._mark_cooldown(mi, f"volume_{label}")

            if snap.last > 0 and base.last > 0:
                px_pct = _pct_change(snap.last, base.last)
                if px_pct is not None:
                    pair = self._thr.price_pct_1m if age <= 60 else self._thr.price_pct_5m
                    sev = _severity_from_thresholds(px_pct, pair)
                    if sev >= 2 and self._cooldown_ok(mi, f"price_{label}"):
                        out.append(
                            ExploitEvent(
                                id=str(uuid.uuid4()),
                                ts=int(snap.ts * 1000),
                                symbol=sym,
                                market_index=mi,
                                kind="price",
                                severity=sev,
                                direction=_direction_from_delta(px_pct),
                                value=px_pct,
                                baseline=base.last,
                                unit="pct",
                                note=f"Price {label} {px_pct:+.2f}%",
                            )
                        )
                        self._mark_cooldown(mi, f"price_{label}")

        if not warm:
            return out

        spread = _spread_bps(snap.bid, snap.ask, snap.mid or snap.last)
        if spread is not None:
            sev = _severity_from_thresholds(spread, self._thr.spread_bps)
            if sev >= 2 and self._cooldown_ok(mi, "spread"):
                out.append(
                    ExploitEvent(
                        id=str(uuid.uuid4()),
                        ts=int(snap.ts * 1000),
                        symbol=sym,
                        market_index=mi,
                        kind="spread",
                        severity=sev,
                        direction="wide",
                        value=spread,
                        baseline=None,
                        unit="bps",
                        note=f"Spread {spread:.0f} bps",
                    )
                )
                self._mark_cooldown(mi, "spread")

        premium = snap.premium
        if premium == 0 and snap.index > 0 and snap.mark > 0:
            premium = (snap.mark - snap.index) / snap.index * 100.0
        if premium:
            sev = _severity_from_thresholds(premium, self._thr.premium_pct)
            if sev >= 2 and self._cooldown_ok(mi, "premium"):
                out.append(
                    ExploitEvent(
                        id=str(uuid.uuid4()),
                        ts=int(snap.ts * 1000),
                        symbol=sym,
                        market_index=mi,
                        kind="premium",
                        severity=sev,
                        direction=_direction_from_delta(premium),
                        value=premium,
                        baseline=to_float(meta.index_price),
                        unit="pct",
                        note=f"Mark-index premium {premium:+.2f}%",
                    )
                )
                self._mark_cooldown(mi, "premium")

        ref = snap.mid or snap.last or snap.mark
        disloc = 0.0
        parts: list[str] = []
        for label, px in (("mark", snap.mark), ("last", snap.last)):
            bps = _bps_diff(px, ref, ref) if px > 0 else None
            if bps is not None and bps >= self._thr.disloc_bps.sev2:
                disloc = max(disloc, bps)
                parts.append(label)
        if disloc >= self._thr.disloc_bps.sev2 and self._cooldown_ok(mi, "dislocation"):
            sev = _severity_from_thresholds(disloc, self._thr.disloc_bps)
            out.append(
                ExploitEvent(
                    id=str(uuid.uuid4()),
                    ts=int(snap.ts * 1000),
                    symbol=sym,
                    market_index=mi,
                    kind="dislocation",
                    severity=sev,
                    direction="skew",
                    value=disloc,
                    baseline=ref,
                    unit="bps",
                    note=f"{'/'.join(parts)} vs mid {disloc:.0f} bps",
                )
            )
            self._mark_cooldown(mi, "dislocation")

        funding_pct_hr = abs(snap.funding) * 100.0
        if funding_pct_hr >= self._thr.funding_hourly_pct.sev2 and self._cooldown_ok(mi, "funding"):
            sev = _severity_from_thresholds(funding_pct_hr, self._thr.funding_hourly_pct)
            direction = "long_pays" if snap.funding > 0 else "short_pays"
            out.append(
                ExploitEvent(
                    id=str(uuid.uuid4()),
                    ts=int(snap.ts * 1000),
                    symbol=sym,
                    market_index=mi,
                    kind="funding",
                    severity=sev,
                    direction=direction,
                    value=funding_pct_hr if snap.funding >= 0 else -funding_pct_hr,
                    baseline=None,
                    unit="pct_hr",
                    note=f"Funding {snap.funding * 100:.4f}%/hr",
                )
            )
            self._mark_cooldown(mi, "funding")

        return out
