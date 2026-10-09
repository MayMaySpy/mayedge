from __future__ import annotations

import logging
import math
import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mayedge.alert_outcomes import OutcomeBook
from mayedge.alert_setups import (
    FactorView,
    PriceContext,
    build_note,
    classify_setup,
    setup_direction,
)
from mayedge.alert_stats import (
    LevelBook,
    MinuteBook,
    market_beta,
    noise_sigma,
    rvol_score,
    z_score,
)
from mayedge.config import settings
from mayedge.lighter.models import Candle, MarketMeta, to_float

logger = logging.getLogger(__name__)

_RING = 500
_SNAPSHOT_MAX = 400
_BOARD_ROWS = 10
_MINUTES_PER_DAY = 1440
_STALE_S = 90.0
_EXCLUDE_RECENT = 5
# One row for a move shared by the whole board. The symbol opens BTC.
BROAD_INDEX = -1
BROAD_SYMBOL = "BTC"


@dataclass(frozen=True)
class SevPair:
    sev2: float
    sev3: float


@dataclass
class AlertSettings:
    min_severity: int = 2
    max_events_per_flush: int = 20
    warmup_s: float = 20.0
    bars_1m: int = 240
    min_bars: int = 30
    level_window_min: int = 1440
    level_min_samples: int = 30
    min_24h_usd: float = 1_000_000.0
    max_spread_bps: float = 40.0
    vol_rvol: SevPair = field(default_factory=lambda: SevPair(4.0, 8.0))
    vol_min_usd_1m: float = 50_000.0
    price_sigma: SevPair = field(default_factory=lambda: SevPair(4.0, 6.0))
    price_min_pct_1m: float = 0.3
    price_min_pct_5m: float = 0.6
    price_sigma_floor_pct: float = 0.05
    oi_sigma: SevPair = field(default_factory=lambda: SevPair(4.0, 6.0))
    oi_min_usd: float = 250_000.0
    oi_sigma_floor_pct: float = 0.3
    premium_sigma: SevPair = field(default_factory=lambda: SevPair(4.0, 6.0))
    premium_sigma_floor_pct: float = 0.05
    disloc_sigma: SevPair = field(default_factory=lambda: SevPair(4.0, 6.0))
    disloc_min_bps: float = 25.0
    disloc_sigma_floor_bps: float = 10.0
    funding_sigma: SevPair = field(default_factory=lambda: SevPair(3.0, 5.0))
    funding_sigma_floor: float = 0.002
    liq_oi_bps: SevPair = field(default_factory=lambda: SevPair(20.0, 60.0))
    liq_min_usd: float = 100_000.0
    liq_window_s: float = 120.0
    score_sev2: float = 4.0
    score_sev3: float = 7.0
    score_exit: float = 2.0
    score_cap: float = 12.0
    board_min: float = 2.5
    board_ttl_s: float = 60.0
    episode_quiet_s: float = 180.0
    episode_rearm_s: float = 600.0
    max_new_per_min: int = 6
    vol_score_cap: float = 6.0
    price_recent_bars: int = 30
    broad_min_markets: int = 15
    broad_move_pct: float = 0.3
    broad_breadth: float = 0.6
    broad_beta_max: float = 3.0
    outcome_horizons: tuple[int, ...] = (5, 15)
    outcome_retention_days: int = 30


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


def _ints(raw: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    if isinstance(raw, (list, tuple)) and raw:
        out: list[int] = []
        for item in raw:
            try:
                n = int(item)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out.append(n)
        if out:
            return tuple(out)
    return default


def thresholds_from_dict(data: dict[str, Any] | None) -> AlertSettings:
    d = data or {}
    base = AlertSettings()
    baseline = d.get("baseline") or {}
    liq = d.get("liquidity") or {}
    factors = d.get("factors") or {}
    vol = factors.get("volume") or {}
    price = factors.get("price") or {}
    oi = factors.get("oi") or {}
    prem = factors.get("premium") or {}
    disloc = factors.get("dislocation") or {}
    funding = factors.get("funding") or {}
    liq_f = factors.get("liq_cluster") or {}
    score = d.get("score") or {}
    episode = d.get("episode") or {}
    broad = d.get("broad") or {}
    outcomes = d.get("outcomes") or {}
    price_min = _pair(price.get("min_pct"), SevPair(base.price_min_pct_1m, base.price_min_pct_5m))
    return AlertSettings(
        min_severity=max(1, min(3, int(_f(d.get("min_severity"), base.min_severity)))),
        max_events_per_flush=max(
            1, int(_f(d.get("max_events_per_flush"), base.max_events_per_flush))
        ),
        warmup_s=_f(d.get("warmup_s"), base.warmup_s),
        bars_1m=int(_f(baseline.get("bars_1m"), base.bars_1m)),
        min_bars=int(_f(baseline.get("min_bars"), base.min_bars)),
        level_window_min=int(_f(baseline.get("level_window_min"), base.level_window_min)),
        level_min_samples=int(_f(baseline.get("level_min_samples"), base.level_min_samples)),
        min_24h_usd=_f(liq.get("min_24h_usd"), base.min_24h_usd),
        max_spread_bps=_f(liq.get("max_spread_bps"), base.max_spread_bps),
        vol_rvol=_pair(vol.get("rvol"), base.vol_rvol),
        vol_min_usd_1m=_f(vol.get("min_usd_1m"), base.vol_min_usd_1m),
        price_sigma=_pair(price.get("sigma"), base.price_sigma),
        price_min_pct_1m=price_min.sev2,
        price_min_pct_5m=price_min.sev3,
        price_sigma_floor_pct=_f(price.get("sigma_floor_pct"), base.price_sigma_floor_pct),
        oi_sigma=_pair(oi.get("sigma"), base.oi_sigma),
        oi_min_usd=_f(oi.get("min_usd"), base.oi_min_usd),
        oi_sigma_floor_pct=_f(oi.get("sigma_floor_pct"), base.oi_sigma_floor_pct),
        premium_sigma=_pair(prem.get("sigma"), base.premium_sigma),
        premium_sigma_floor_pct=_f(prem.get("sigma_floor_pct"), base.premium_sigma_floor_pct),
        disloc_sigma=_pair(disloc.get("sigma"), base.disloc_sigma),
        disloc_min_bps=_f(disloc.get("min_bps"), base.disloc_min_bps),
        disloc_sigma_floor_bps=_f(disloc.get("sigma_floor_bps"), base.disloc_sigma_floor_bps),
        funding_sigma=_pair(funding.get("sigma"), base.funding_sigma),
        funding_sigma_floor=_f(funding.get("sigma_floor"), base.funding_sigma_floor),
        liq_oi_bps=_pair(liq_f.get("oi_bps"), base.liq_oi_bps),
        liq_min_usd=_f(liq_f.get("min_usd"), base.liq_min_usd),
        liq_window_s=_f(liq_f.get("window_s"), base.liq_window_s),
        score_sev2=_f(score.get("sev2"), base.score_sev2),
        score_sev3=_f(score.get("sev3"), base.score_sev3),
        score_exit=_f(score.get("exit"), base.score_exit),
        score_cap=_f(score.get("cap"), base.score_cap),
        board_min=_f(score.get("board_min"), base.board_min),
        episode_quiet_s=_f(episode.get("quiet_s"), base.episode_quiet_s),
        episode_rearm_s=_f(episode.get("rearm_s"), base.episode_rearm_s),
        max_new_per_min=int(_f(episode.get("max_new_per_min"), base.max_new_per_min)),
        vol_score_cap=_f(vol.get("score_cap"), base.vol_score_cap),
        price_recent_bars=int(_f(price.get("recent_bars"), base.price_recent_bars)),
        broad_min_markets=int(_f(broad.get("min_markets"), base.broad_min_markets)),
        broad_move_pct=_f(broad.get("move_pct"), base.broad_move_pct),
        broad_breadth=_f(broad.get("breadth"), base.broad_breadth),
        broad_beta_max=_f(broad.get("beta_max"), base.broad_beta_max),
        outcome_horizons=_ints(outcomes.get("horizons_min"), base.outcome_horizons),
        outcome_retention_days=int(_f(outcomes.get("retention_days"), base.outcome_retention_days)),
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


@dataclass
class Factor:
    kind: str
    direction: str
    value: float
    unit: str
    score: float
    window: str = ""
    excess: float | None = None

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "kind": self.kind,
            "direction": self.direction,
            "value": self.value,
            "unit": self.unit,
            "score": round(self.score, 2),
        }
        if self.window:
            row["window"] = self.window
        if self.excess is not None:
            row["excess"] = round(self.excess, 2)
        return row


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
    score: float | None = None
    setup: str | None = None
    factors: list[dict[str, Any]] | None = None
    started_at: int | None = None

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
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
        if self.score is not None:
            row["score"] = round(self.score, 2)
        if self.setup:
            row["setup"] = self.setup
        if self.factors:
            row["factors"] = self.factors
        if self.started_at is not None:
            row["started_at"] = self.started_at
        return row


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


def _direction_from_delta(delta: float) -> str:
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


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


def composite_score(factors: list[Factor]) -> float:
    if not factors:
        return 0.0
    ordered = sorted(factors, key=lambda f: f.score, reverse=True)
    total = ordered[0].score
    if len(ordered) > 1:
        total += 0.5 * ordered[1].score
    if len(ordered) > 2:
        total += 0.25 * ordered[2].score
    return total


def confirming_count(factors: list[Factor]) -> int:
    """Volume confirms a move. It does not, by itself, make one urgent."""
    return sum(1 for f in factors if f.kind != "volume")


def _breadth(factors: list[Factor]) -> list[int] | None:
    for factor in factors:
        if factor.kind != "broad" or "/" not in factor.window:
            continue
        left, right = factor.window.split("/", 1)
        try:
            return [int(left), int(right)]
        except ValueError:
            return None
    return None


def severity_from_score(score: float, confirming: int, cfg: AlertSettings) -> int:
    if score >= cfg.score_sev3 or (score >= 5.0 and confirming >= 2):
        return 3
    if score >= cfg.score_sev2:
        return 2
    return 1


def _views(factors: list[Factor]) -> list[FactorView]:
    return [FactorView(f.kind, f.direction, f.value, f.score, f.window) for f in factors]


def _strongest_per_kind(factors: list[Factor]) -> list[Factor]:
    """1m and 5m readings of the same thing must not count twice in the composite."""
    best: dict[str, Factor] = {}
    for f in factors:
        prev = best.get(f.kind)
        if prev is None or f.score > prev.score:
            best[f.kind] = f
    return sorted(best.values(), key=lambda f: -f.score)


@dataclass
class _Episode:
    id: str
    market_index: int
    symbol: str
    started_ms: int
    peak_score: float
    last_active: float
    factors: list[Factor]
    setup: str
    direction: str
    score: float
    severity: int


class EpisodeBook:
    def __init__(self, cfg: AlertSettings) -> None:
        self._cfg = cfg
        self._active: dict[int, _Episode] = {}
        self._closed_peak: dict[int, tuple[float, float]] = {}
        self._new_episode_times: deque[float] = deque()
        self._board: dict[int, dict[str, Any]] = {}

    def board_rows(self, now: float | None = None) -> list[dict[str, Any]]:
        cutoff_ms = int(((now if now is not None else time.time()) - self._cfg.board_ttl_s) * 1000)
        for mi in [mi for mi, row in self._board.items() if int(row["ts"]) < cutoff_ms]:
            del self._board[mi]
        rows = sorted(self._board.values(), key=lambda r: float(r["score"]), reverse=True)
        return rows[:_BOARD_ROWS]

    def _rate_ok(self, now: float) -> bool:
        while self._new_episode_times and now - self._new_episode_times[0] > 60.0:
            self._new_episode_times.popleft()
        return len(self._new_episode_times) < self._cfg.max_new_per_min

    def ingest(
        self,
        market_index: int,
        symbol: str,
        factors: list[Factor],
        now: float,
        *,
        liquidity_ok: bool,
        context: PriceContext | None = None,
    ) -> ExploitEvent | None:
        factors = [f for f in factors if f.score >= self._cfg.score_exit]
        score = composite_score(factors)
        self._update_board(market_index, symbol, factors, score, now, liquidity_ok, context)
        if not liquidity_ok:
            return None

        ep = self._active.get(market_index)
        if score < self._cfg.score_exit:
            if ep and now - ep.last_active >= self._cfg.episode_quiet_s:
                self._close(market_index, now)
            return None

        if ep is None:
            if score < self._cfg.score_sev2 or not self._can_open(market_index, score, now):
                return None
            if not self._rate_ok(now):
                return None
            self._new_episode_times.append(now)
            ep = _Episode(
                id=f"sig-{market_index}-{int(now)}",
                market_index=market_index,
                symbol=symbol,
                started_ms=int(now * 1000),
                peak_score=score,
                last_active=now,
                factors=sorted(factors, key=lambda f: -f.score),
                setup="",
                direction="flat",
                score=score,
                severity=1,
            )
            self._active[market_index] = ep
            self._refresh(ep, context)
            return self._event(ep, now)

        before = (round(ep.score, 1), ep.setup, len(ep.factors))
        ep.factors = self._merge_factors(ep.factors, factors)
        ep.last_active = now
        self._refresh(ep, context)
        if (round(ep.score, 1), ep.setup, len(ep.factors)) == before:
            return None
        return self._event(ep, now)

    def _refresh(self, ep: _Episode, context: PriceContext | None) -> None:
        views = _views(ep.factors)
        ep.score = composite_score(ep.factors)
        ep.peak_score = max(ep.peak_score, ep.score)
        ep.setup = classify_setup(views, context)
        ep.direction = setup_direction(views, context)
        ep.severity = severity_from_score(ep.score, confirming_count(ep.factors), self._cfg)

    def _update_board(
        self,
        market_index: int,
        symbol: str,
        factors: list[Factor],
        score: float,
        now: float,
        liquidity_ok: bool,
        context: PriceContext | None,
    ) -> None:
        if not liquidity_ok or score < self._cfg.board_min:
            self._board.pop(market_index, None)
            return
        views = _views(factors)
        row: dict[str, Any] = {
            "market_index": market_index,
            "symbol": symbol,
            "score": round(score, 2),
            "severity": severity_from_score(score, confirming_count(factors), self._cfg),
            "setup": classify_setup(views, context),
            "direction": setup_direction(views, context),
            "factors": [f.as_dict() for f in sorted(factors, key=lambda x: -x.score)[:4]],
            "move_pct": round(context.move_pct, 2) if context else None,
            "ts": int(now * 1000),
        }
        breadth = _breadth(factors)
        if breadth is not None:
            row["breadth"] = breadth
        self._board[market_index] = row

    def _can_open(self, market_index: int, score: float, now: float) -> bool:
        closed = self._closed_peak.get(market_index)
        if closed is None:
            return True
        closed_at, peak = closed
        if now - closed_at < self._cfg.episode_rearm_s:
            return score >= peak + 2.0
        return True

    def _close(self, market_index: int, now: float) -> None:
        ep = self._active.pop(market_index, None)
        if ep:
            self._closed_peak[market_index] = (now, ep.peak_score)

    @staticmethod
    def _merge_factors(existing: list[Factor], incoming: list[Factor]) -> list[Factor]:
        return _strongest_per_kind([*existing, *incoming])

    def _event(self, ep: _Episode, now: float) -> ExploitEvent:
        factor_dicts = [f.as_dict() for f in ep.factors]
        top = ep.factors[0] if ep.factors else None
        return ExploitEvent(
            id=ep.id,
            ts=int(now * 1000),
            symbol=ep.symbol,
            market_index=ep.market_index,
            kind="signal",
            severity=ep.severity,
            direction=ep.direction,
            value=ep.score,
            baseline=top.value if top else None,
            unit="score",
            note=build_note(ep.setup, factor_dicts),
            score=ep.score,
            setup=ep.setup,
            factors=factor_dicts,
            started_at=ep.started_ms,
        )


class ExploitDetector:
    """Relative outlier scanner with composite episodes."""

    def __init__(
        self,
        broadcast: Callable[[dict[str, Any]], None],
        thresholds: AlertSettings | None = None,
    ) -> None:
        self._broadcast = broadcast
        self._thr = thresholds if thresholds is not None else load_thresholds()
        self._ring: list[dict[str, Any]] = []
        self._snapshots: dict[int, deque[MarketSnapshot]] = {}
        self._seen_since: dict[int, float] = {}
        self._liq_window: dict[int, deque[tuple[float, float, str, str]]] = {}
        self._pending: list[ExploitEvent] = []
        self._minute = MinuteBook(
            max_bars=self._thr.bars_1m,
            min_bars=self._thr.min_bars,
            sigma_floor_pct=self._thr.price_sigma_floor_pct,
        )
        self._level = LevelBook(
            window_min=self._thr.level_window_min,
            min_samples=self._thr.level_min_samples,
        )
        self._episodes = EpisodeBook(self._thr)
        self._outcomes = OutcomeBook(
            horizons=self._thr.outcome_horizons,
            retention_days=self._thr.outcome_retention_days,
        )
        self._symbols: dict[int, str] = {}
        self._noise_cache: dict[int, tuple[tuple[int, int], float, float]] = {}
        self._broad_minute = -1
        self._broad_markets = -1
        self._broad_cache: dict[int, float] | None = None
        self._rvol_cache: tuple[float, float] | None = None
        self._moves_cache: dict[float, tuple[float, list[float]]] = {}

    def recent(self) -> list[dict[str, Any]]:
        return list(self._ring)

    def board(self) -> list[dict[str, Any]]:
        return self._episodes.board_rows()

    def outcome_stats(self, *, hours: int) -> dict[str, Any]:
        since = int((time.time() - hours * 3600) * 1000)
        return {"hours": hours, "setups": self._outcomes.stats(since_ms=since)}

    def minute_book(self) -> MinuteBook:
        return self._minute

    def seed_minute_bars(self, market_index: int, bars: list[Candle]) -> None:
        self._minute.seed(market_index, bars)
        self._resolve_outcomes(market_index, time.time())

    def on_minute_bars(self, market_index: int, bars: list[Candle]) -> None:
        self._minute.observe(market_index, bars)
        self._resolve_outcomes(market_index, time.time())

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

    def _queue(self, events: list[ExploitEvent]) -> None:
        floor = self._thr.min_severity
        for ev in events:
            if ev.severity < floor:
                continue
            self._pending.append(ev)

    def emit_events(self, events: list[ExploitEvent]) -> None:
        if events:
            self._emit(events)

    def flush(self) -> None:
        self._consider_broad(time.time())
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
        self._symbols[meta.market_index] = meta.symbol
        snap = self._snapshot_from_meta(meta)
        if snap is None:
            return
        if not self._record_snapshot(meta.market_index, snap):
            return
        factors, context = self._scan_factors(meta, snap)
        ev = self._episodes.ingest(
            meta.market_index,
            meta.symbol,
            factors,
            snap.ts,
            liquidity_ok=self._liquidity_ok(snap),
            context=context,
        )
        if ev:
            self._track_new_episode(ev, snap.ts)
            self._queue([ev])

    def on_liquidations(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        now = time.time()
        by_market: dict[int, list[tuple[float, float, str, str]]] = {}
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
            by_market.setdefault(mi, []).append((ts, usd, side, key))

        window_s = self._thr.liq_window_s
        for mi, rows in by_market.items():
            window = self._liq_window.setdefault(mi, deque())
            for ts, usd, side, key in rows:
                window = deque(item for item in window if item[3] != key)
                window.append((ts, usd, side, key))
            cutoff = now - window_s
            window = deque(
                sorted((item for item in window if item[0] >= cutoff), key=lambda r: r[0])
            )
            self._liq_window[mi] = window
            if not window:
                continue
            series = self._snapshots.get(mi)
            if not series:
                continue
            snap = series[-1]
            total_usd = sum(r[1] for r in window)
            if total_usd < self._thr.liq_min_usd or snap.oi <= 0:
                continue
            oi_bps = total_usd / snap.oi * 10_000.0
            if oi_bps < self._thr.liq_oi_bps.sev2:
                continue
            symbol = self._symbols.get(mi, f"M{mi}")
            sells = sum(1 for _, _, s, _ in window if s == "sell")
            factor = Factor(
                kind="liq_cluster",
                direction="down" if sells >= len(window) / 2 else "up",
                value=total_usd,
                unit="usd",
                score=min(
                    oi_bps / self._thr.liq_oi_bps.sev2 * self._thr.score_sev2, self._thr.score_cap
                ),
            )
            ev = self._episodes.ingest(
                mi, symbol, [factor], now, liquidity_ok=self._liquidity_ok(snap)
            )
            if ev:
                self._track_new_episode(ev, now)
                self._queue([ev])
        self.flush()

    def _warm(self, market_index: int, now: float) -> bool:
        first = self._seen_since.get(market_index)
        if first is None:
            return False
        return now - first >= self._thr.warmup_s

    def _liquidity_ok(self, snap: MarketSnapshot) -> bool:
        if snap.vol_quote < self._thr.min_24h_usd:
            return False
        spread = _spread_bps(snap.bid, snap.ask, snap.mid or snap.last)
        return spread is None or spread <= self._thr.max_spread_bps

    def _resolve_outcomes(self, market_index: int, now: float) -> None:
        if not self._outcomes.awaiting(market_index):
            return
        self._outcomes.resolve(
            market_index,
            self._minute.bars(market_index),
            self._broad_series(now),
            now=now,
        )

    def _track_new_episode(self, ev: ExploitEvent, now: float) -> None:
        if ev.started_at != ev.ts or ev.direction not in ("up", "down"):
            return
        if ev.market_index == BROAD_INDEX:
            minute = int(now // 60) * 60
            self._outcomes.open(
                episode_id=ev.id,
                market_index=BROAD_INDEX,
                symbol=ev.symbol,
                setup=ev.setup or "",
                direction=ev.direction,
                entry_bar=minute - 60,
                entry_close=100.0,
                beta=0.0,
                opened_at=ev.started_at or int(now * 1000),
            )
            return
        entry = self._entry_bar(ev.market_index, now)
        if entry is None:
            return
        beta, _sigma = self._noise(ev.market_index, now)
        self._outcomes.open(
            episode_id=ev.id,
            market_index=ev.market_index,
            symbol=ev.symbol,
            setup=ev.setup or "",
            direction=ev.direction,
            entry_bar=entry[0],
            entry_close=entry[1],
            beta=beta,
            opened_at=ev.started_at or int(now * 1000),
        )

    def _entry_bar(self, market_index: int, now: float) -> tuple[int, float] | None:
        minute = int(now // 60) * 60
        closed = [
            bar for bar in self._minute.bars(market_index) if bar.time < minute and bar.close > 0
        ]
        if not closed:
            return None
        bar = closed[-1]
        return bar.time, bar.close

    def _consider_broad(self, now: float) -> None:
        moves = self._live_moves(300.0, now)
        n = len(moves)
        thr = self._thr
        if n < thr.broad_min_markets:
            return
        move = statistics.median(moves)
        if abs(move) < thr.price_min_pct_5m:
            return
        series = self._broad_series(now)
        ordered = [series[t] for t in sorted(series)]
        if len(ordered) < thr.min_bars:
            return
        sigma = noise_sigma(
            ordered,
            recent_bars=thr.price_recent_bars,
            exclude_recent=_EXCLUDE_RECENT,
            floor=thr.price_sigma_floor_pct,
        )
        z = z_score(move, 0.0, sigma * math.sqrt(5))
        if abs(z) < thr.price_sigma.sev2:
            return
        direction = _direction_from_delta(move)
        if direction == "up":
            same = sum(1 for item in moves if item > thr.broad_move_pct)
        else:
            same = sum(1 for item in moves if item < -thr.broad_move_pct)
        if same / n < thr.broad_breadth:
            return
        factor = Factor(
            "broad",
            direction,
            move,
            "pct",
            min(abs(z), thr.score_cap),
            window=f"{same}/{n}",
        )
        ev = self._episodes.ingest(
            BROAD_INDEX,
            BROAD_SYMBOL,
            [factor],
            now,
            liquidity_ok=True,
            context=PriceContext(move_pct=move, move_sigma=abs(z)),
        )
        if ev:
            self._track_new_episode(ev, now)
            self._queue([ev])

    def _broad_series(self, now: float) -> dict[int, float]:
        minute = int(now // 60)
        markets = self._minute.market_count()
        if (
            self._broad_cache is not None
            and self._broad_minute == minute
            and self._broad_markets == markets
        ):
            return self._broad_cache
        series = self._minute.broad_returns(min_markets=self._thr.broad_min_markets)
        self._broad_minute = minute
        self._broad_markets = markets
        self._broad_cache = series
        return series

    def _noise(self, market_index: int, now: float) -> tuple[float, float]:
        minute = int(now // 60)
        series = self._broad_series(now)
        key = (minute, len(series))
        hit = self._noise_cache.get(market_index)
        if hit is not None and hit[0] == key:
            return hit[1], hit[2]
        rets = self._minute.closed_return_map(market_index)
        beta = market_beta(
            rets,
            series,
            min_samples=self._thr.min_bars,
            beta_max=self._thr.broad_beta_max,
        )
        ordered = sorted(rets)
        if series:
            residuals = [rets[t] - beta * series[t] for t in ordered if t in series]
        else:
            residuals = [rets[t] for t in ordered]
        sigma = noise_sigma(
            residuals,
            recent_bars=self._thr.price_recent_bars,
            exclude_recent=_EXCLUDE_RECENT,
            floor=self._thr.price_sigma_floor_pct,
        )
        self._noise_cache[market_index] = (key, beta, sigma)
        return beta, sigma

    def _broad_move(self, age_s: float, now: float) -> float:
        moves = self._live_moves(age_s, now)
        if len(moves) < self._thr.broad_min_markets:
            return 0.0
        return float(statistics.median(moves))

    def _live_moves(self, age_s: float, now: float) -> list[float]:
        hit = self._moves_cache.get(age_s)
        if hit is not None and now - hit[0] < 1.0:
            return hit[1]
        moves: list[float] = []
        for series in self._snapshots.values():
            if not series:
                continue
            snap = series[-1]
            if now - snap.ts > _STALE_S or not self._liquidity_ok(snap):
                continue
            base = self._find_baseline(series, age_s)
            if base is None:
                continue
            pct = _pct_change(snap.last, base.last)
            if pct is not None:
                moves.append(pct)
        self._moves_cache[age_s] = (now, moves)
        return moves

    def _board_rvol(self, now: float) -> float:
        cached = self._rvol_cache
        if cached is not None and now - cached[0] < 1.0:
            return cached[1]
        rvols: list[float] = []
        for market_index, series in self._snapshots.items():
            if not series:
                continue
            snap = series[-1]
            if now - snap.ts > _STALE_S or not self._liquidity_ok(snap):
                continue
            metrics = self._minute.metrics(
                market_index, volume_floor=max(snap.vol_quote, 0.0) / _MINUTES_PER_DAY
            )
            if metrics is None or metrics.rvol_1m <= 0:
                continue
            rvols.append(metrics.rvol_1m)
        if len(rvols) < self._thr.broad_min_markets:
            return 1.0
        med = float(statistics.median(rvols))
        value = med if med > 1.0 else 1.0
        self._rvol_cache = (now, value)
        return value

    def _sigma_factor(
        self,
        kind: str,
        z: float | None,
        pair: SevPair,
        *,
        direction: str,
        value: float,
        unit: str,
        window: str = "",
        excess: float | None = None,
    ) -> Factor | None:
        if z is None or abs(z) < pair.sev2:
            return None
        score = min(abs(z), self._thr.score_cap)
        return Factor(kind, direction, value, unit, score, window=window, excess=excess)

    def _scan_factors(
        self, meta: MarketMeta, snap: MarketSnapshot
    ) -> tuple[list[Factor], PriceContext | None]:
        series = self._snapshots.get(meta.market_index)
        if not series or len(series) < 2:
            return [], None
        thr = self._thr
        out: list[Factor] = []
        mi = meta.market_index
        spread = _spread_bps(snap.bid, snap.ask, snap.mid or snap.last)

        premium = snap.premium
        if premium == 0 and snap.index > 0 and snap.mark > 0:
            premium = (snap.mark - snap.index) / snap.index * 100.0

        # A wide book makes mid meaningless; only score mark-vs-mid on tight books.
        disloc_bps: float | None = None
        if snap.mark > 0 and snap.mid > 0 and spread is not None and spread < thr.max_spread_bps:
            disloc_bps = _bps_diff(snap.mark, snap.mid, snap.mid)

        self._level.observe(
            mi, ts=snap.ts, premium=premium, disloc_bps=disloc_bps, funding=snap.funding, oi=snap.oi
        )

        minute = self._minute.metrics(mi, volume_floor=max(snap.vol_quote, 0.0) / _MINUTES_PER_DAY)
        context: PriceContext | None = None
        beta, noise = self._noise(mi, snap.ts)
        broad_by_label = {
            "1m": self._broad_move(60.0, snap.ts),
            "5m": self._broad_move(300.0, snap.ts),
        }
        board_rvol = self._board_rvol(snap.ts)

        if minute is not None:
            for label, rvol, vol_usd in (
                ("1m", minute.rvol_1m, minute.vol_quote_1m),
                ("5m", minute.rvol_5m, minute.vol_quote_5m),
            ):
                adjusted = rvol / board_rvol if board_rvol > 1.0 else rvol
                score = rvol_score(adjusted)
                if vol_usd < thr.vol_min_usd_1m or score < rvol_score(thr.vol_rvol.sev2):
                    continue
                out.append(
                    Factor(
                        "volume",
                        "up",
                        adjusted,
                        "x",
                        min(score, thr.vol_score_cap, thr.score_cap),
                        window=label,
                    )
                )

        for age, label, min_pct in (
            (60.0, "1m", thr.price_min_pct_1m),
            (300.0, "5m", thr.price_min_pct_5m),
        ):
            base = self._find_baseline(series, age)
            if base is None:
                continue
            if minute is not None:
                px_pct = _pct_change(snap.last, base.last)
                if px_pct is not None:
                    scale = math.sqrt(5) if label == "5m" else 1.0
                    raw_z = z_score(px_pct, 0.0, minute.sigma_1m_pct * scale)
                    if label == "5m":
                        context = PriceContext(move_pct=px_pct, move_sigma=abs(raw_z))
                    excess = px_pct - beta * broad_by_label[label]
                    if abs(px_pct) >= min_pct and abs(excess) >= min_pct:
                        shown = excess if abs(excess - px_pct) >= 0.05 else None
                        factor = self._sigma_factor(
                            "price",
                            z_score(excess, 0.0, noise * scale),
                            thr.price_sigma,
                            direction=_direction_from_delta(excess),
                            value=px_pct,
                            unit="pct",
                            window=label,
                            excess=shown,
                        )
                        if factor:
                            out.append(factor)

            if label == "5m" and snap.oi > 0 and base.oi > 0:
                oi_pct = _pct_change(snap.oi, base.oi)
                if oi_pct is not None and abs(snap.oi - base.oi) >= thr.oi_min_usd:
                    factor = self._sigma_factor(
                        "oi",
                        self._level.z_oi_change_pct(mi, oi_pct, floor=thr.oi_sigma_floor_pct),
                        thr.oi_sigma,
                        direction=_direction_from_delta(oi_pct),
                        value=oi_pct,
                        unit="pct",
                        window="5m",
                    )
                    if factor:
                        out.append(factor)

        if context is None and minute is not None and minute.move_5m_pct is not None:
            z = z_score(minute.move_5m_pct, 0.0, minute.sigma_1m_pct * math.sqrt(5))
            context = PriceContext(move_pct=minute.move_5m_pct, move_sigma=abs(z))

        if not self._warm(mi, snap.ts):
            return _strongest_per_kind(out), context

        if premium:
            factor = self._sigma_factor(
                "premium",
                self._level.z_premium(mi, premium, floor=thr.premium_sigma_floor_pct),
                thr.premium_sigma,
                direction=_direction_from_delta(premium),
                value=premium,
                unit="pct",
            )
            if factor:
                out.append(factor)

        if disloc_bps is not None and disloc_bps >= thr.disloc_min_bps:
            factor = self._sigma_factor(
                "dislocation",
                self._level.z_disloc(mi, disloc_bps, floor=thr.disloc_sigma_floor_bps),
                thr.disloc_sigma,
                direction=_direction_from_delta(snap.mark - snap.mid),
                value=disloc_bps,
                unit="bps",
            )
            if factor:
                out.append(factor)

        if snap.funding:
            factor = self._sigma_factor(
                "funding",
                self._level.z_funding(mi, snap.funding, floor=thr.funding_sigma_floor),
                thr.funding_sigma,
                direction="up" if snap.funding > 0 else "down",
                value=snap.funding,
                unit="pct_hr",
            )
            if factor:
                out.append(factor)

        return _strongest_per_kind(out), context
