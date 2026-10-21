"""Alerts, the funding strip and the Activity board.

The rules are docs/alert-rules.md; rule ids are in comments.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from mayedge.alert_log import AlertLog
from mayedge.alert_rows import (
    _MULTIPLE_CAP,
    NOTABLE,
    SPIKE_KINDS,
    STATE_KINDS,
    URGENT,
    AlertEvent,
    Broad,
    Fact,
    Held,
    MarketSnapshot,
    RowBook,
    describe,
)
from mayedge.alert_settings import (
    AlertSettings,
    load_thresholds,
    resolve_alerts_config_path,
    thresholds_from_dict,
)
from mayedge.alert_stats import HourBase, LevelBook, MinuteBook
from mayedge.lighter.models import Candle, MarketMeta, to_float

logger = logging.getLogger(__name__)

_RING = 500
_SNAPSHOT_MAX = 400
_MINUTES_PER_DAY = 1440
_STALE_S = 90.0
# One row for a move shared by the board. The symbol opens BTC.
BROAD_INDEX = -1
BROAD_SYMBOL = "BTC"
# R7: this close to the day's high or low counts as at it.
_AT_EXTREME_BPS = 2.0
_PREMIUM_FLOOR_PCT = 0.05


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

    def seed_levels(self, name: str, by_market: Mapping[int, Iterable[tuple[int, float]]]) -> None:
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
        rows = [row for row in self.iter_funding_extremes() if row is not None]
        rows.sort(key=lambda row: (-abs(float(row["z"])), str(row["symbol"])))
        return rows

    def iter_funding_extremes(self) -> Iterator[dict[str, Any] | None]:
        """One market at a time, so the Scan loop can breathe between them."""
        now = time.time()
        held = self._held_book(now)
        for mi, series in self._snapshots.items():
            snap = series[-1]
            if now - snap.ts > _STALE_S or not (mi in held or self._liquidity_ok(snap)):
                yield None
                continue
            z = self._funding_z(mi, snap)
            if z is None:
                yield None
                continue
            yield {
                "market_index": mi,
                "symbol": self._symbols.get(mi, f"M{mi}"),
                "funding": snap.funding,
                "z": round(z, 2),
                "held": mi in held,
            }

    def activity(self) -> list[dict[str, Any]]:
        """A1, A2: every liquid perp and what its tape shows now."""
        rows = [row for row in self.iter_activity() if row is not None]
        rows.sort(key=lambda row: str(row["symbol"]))
        return rows

    def iter_activity(self) -> Iterator[dict[str, Any] | None]:
        """One market at a time, so the Scan loop can breathe between them."""
        now = time.time()
        held = self._held_book(now)
        for mi, series in self._snapshots.items():
            snap = series[-1]
            if now - snap.ts > _STALE_S or not self._liquidity_ok(snap):
                yield None
                continue
            day = self._day_range(snap)
            base = self._find_baseline(series, 300.0)
            move = _pct_change(snap.last, base.last) if base else None
            metrics = self._minute.metrics(mi, volume_floor=snap.vol_quote / _MINUTES_PER_DAY)
            oi_pct = _pct_change(snap.oi, base.oi) if base else None
            premium = self._premium(snap)
            yield {
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


__all__ = [
    "BROAD_INDEX",
    "BROAD_SYMBOL",
    "NOTABLE",
    "SPIKE_KINDS",
    "STATE_KINDS",
    "URGENT",
    "AlertDetector",
    "AlertEvent",
    "AlertSettings",
    "Broad",
    "Fact",
    "Held",
    "MarketSnapshot",
    "RowBook",
    "describe",
    "load_thresholds",
    "resolve_alerts_config_path",
    "thresholds_from_dict",
]
