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
from mayedge.alert_stats import LevelBook, MinuteBook, SpanBase, completed_extremes
from mayedge.lighter.models import Candle, MarketMeta, to_float

logger = logging.getLogger(__name__)

_RING = 500
_SNAPSHOT_MAX = 400
_MINUTES_PER_DAY = 1440
_STALE_S = 90.0
# The Board line opens BTC. Board rows from before ADR 0027 carry this index.
BROAD_INDEX = -1
BROAD_SYMBOL = "BTC"
# M1: the spans a Move is judged over, in minutes.
SPANS = (1, 5, 15)
# M6: a span's volume is said once it is this many times its mean.
_VOLUME_SAID_X = 2.0
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


def _multiple(value: float, usual: float) -> float:
    """How many times its usual this is. A usual of nothing reads as the cap."""
    if usual <= 0:
        return _MULTIPLE_CAP
    return min(value / usual, _MULTIPLE_CAP)


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
    "move.x": "move_x",
    "liquidations.min_usd": "liq_min_usd",
    "liquidations.oi_bps": "liq_oi_bps",
    "held.liq_distance_pct": "held_liq_distance_pct",
}


class AlertDetector:
    """Moves and states that raise rows, the Board line, the funding strip and the Activity board."""

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
        self._daily: dict[int, list[Candle]] = {}
        self._daily_day: dict[int, int] = {}
        self._broad_cache: tuple[float, Broad | None] | None = None
        # W3: the UTC day each level last broke, per market.
        self._broken: dict[tuple[int, str], int] = {}

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

    def daily_current(self, market_index: int, day: int) -> bool:
        """True once this UTC day has seeded the week and quarter levels."""
        return self._daily_day.get(market_index) == day

    def daily_bars(self, market_index: int) -> list[Candle]:
        """The daily bars W1 reads, for the Setups board (setup-rules X4, X5)."""
        return list(self._daily.get(market_index) or [])

    def seed_daily_bars(self, market_index: int, bars: list[Candle], now: float) -> None:
        """W1. Daily bars the week and quarter are read from. Today is dropped at read time."""
        self._daily[market_index] = list(bars)
        self._daily_day[market_index] = int(now) // 86_400

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
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        self._emit(pending)

    def board_line(self) -> dict[str, Any] | None:
        """B3: the Board line above the list, while the Broad move is big enough. Not a row."""
        broad = self._broad(time.time())
        if broad is None or abs(broad.move_5m) < self._thr.board_median_pct:
            return None
        return {
            "direction": broad.direction,
            "move_5m": round(broad.move_5m, 4),
            "same": broad.same,
            "movers": broad.movers,
            "liquid": broad.liquid,
        }

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
        # G2, G3, G4.
        if held is not None or (self._liquidity_ok(snap) and self._live(market_index, now)):
            facts.extend(self._move_facts(market_index, snap, now))
            for fact in (
                self._liq_fact(market_index, snap, now),
                self._near_liq_fact(snap, held),
                *self._range_facts(market_index, now),
            ):
                if fact is not None:
                    facts.append(fact)
        fired = [f for f in facts if f.size is not None]
        if not fired:
            return
        context = [f for f in facts if f.size is None]
        # R5: a row that is not a Move still says the minute.
        if not any(f.kind == "move" for f in facts):
            minute = self._span_move(market_index, snap, 1, now)
            if minute is not None:
                context.append(minute)
        # R7, R8.
        context.extend(self._tags(market_index, snap))
        label = "" if held is None else (held.side or "order")
        ev = self._rows.ingest(
            market_index, symbol, fired, context, now, price=snap.last, held=label
        )
        if ev:
            self._record(ev, now)

    def _live(self, market_index: int, now: float) -> bool:
        """G4."""
        share = self._minute.live_share(market_index, now=now, bars=self._thr.move_usual_bars)
        return share is not None and share >= self._thr.move_live_share

    def _floor(self, span: int) -> float:
        return {
            1: self._thr.move_floor_1m_pct,
            5: self._thr.move_floor_5m_pct,
        }.get(span, self._thr.move_floor_15m_pct)

    def _span_move(
        self, market_index: int, snap: MarketSnapshot, span: int, now: float
    ) -> Fact | None:
        """The plain move over a span, from the close ``span`` bars back."""
        base = self._minute.span(market_index, span, now=now, bars=self._thr.move_usual_bars)
        if base is None:
            return None
        pct = _pct_change(snap.last, base.ref_close)
        if pct is None:
            return None
        return Fact("move", _direction(pct), pct, "pct", window=f"{span}m")

    def _move_facts(self, market_index: int, snap: MarketSnapshot, now: float) -> list[Fact]:
        """M1 to M4, M6. The span furthest past its threshold, and what the tape said with it."""
        best: tuple[Fact, SpanBase] | None = None
        broad = self._broad(now)
        for span in SPANS:
            base = self._minute.span(market_index, span, now=now, bars=self._thr.move_usual_bars)
            if base is None:
                continue
            pct = _pct_change(snap.last, base.ref_close)
            if pct is None:
                continue
            judged = pct
            excess: float | None = None
            # M4: with the board, only the part beyond it counts.
            if broad is not None and _direction(pct) == broad.direction:
                board = broad.spans.get(span, 0.0)
                if _direction(board) == broad.direction:
                    judged = pct - board
                    if _direction(judged) != broad.direction:
                        continue
                    excess = judged
            threshold = max(self._thr.move_x * base.usual_pct, self._floor(span))
            if abs(judged) < threshold:
                continue
            fact = Fact("move", _direction(pct), pct, "pct", window=f"{span}m")
            fact.size = abs(judged) / threshold
            fact.detail["multiple"] = _multiple(abs(judged), base.usual_pct)
            fact.detail["usual"] = base.usual_pct
            fact.detail["share"] = abs(pct) / self._day_range(snap)
            if excess is not None:
                fact.detail["excess"] = excess
            if best is None or (fact.size or 0.0) > (best[0].size or 0.0):
                best = (fact, base)
        if best is None:
            return []
        fact, base = best
        out = [fact]
        # M6.
        if base.mean_volume_usd > 0:
            vol_x = base.volume_usd / base.mean_volume_usd
            if vol_x >= _VOLUME_SAID_X:
                out.append(
                    Fact(
                        "volume",
                        "flat",
                        base.volume_usd,
                        "usd",
                        window=fact.window,
                        detail={"multiple": min(vol_x, _MULTIPLE_CAP)},
                    )
                )
        then = self._level.back(market_index, "oi", now=now, minutes=base.span)
        if then and snap.oi > 0:
            delta = snap.oi - then
            out.append(
                Fact(
                    "oi",
                    _direction(delta),
                    delta / then * 100.0,
                    "pct",
                    window=fact.window,
                    detail={"usd": delta},
                )
            )
        return out

    def _range_facts(self, market_index: int, now: float) -> list[Fact]:
        """W1 to W3. A closed minute through a level, once a UTC day. Quarter before week."""
        bars = self._daily.get(market_index)
        closed = self._minute.bars(market_index)
        minute = int(now // 60) * 60
        closed = [bar for bar in closed if bar.time < minute][-2:]
        if not bars or len(closed) < 2:
            return []
        before, last = closed
        day = int(now) // 86_400
        out: list[Fact] = []
        windows = (
            (self._thr.range_quarter_days, "quarter_high", "quarter_low"),
            (self._thr.range_week_days, "week_high", "week_low"),
        )
        for days, high_kind, low_kind in windows:
            extremes = completed_extremes(bars, now=now, days=days)
            if extremes is None:
                continue
            high, low = extremes
            for level, kind, direction in ((high, high_kind, "up"), (low, low_kind, "down")):
                if level <= 0:
                    continue
                if direction == "up":
                    through = last.close > level >= before.close
                else:
                    through = last.close < level <= before.close
                if not through or self._broken.get((market_index, kind)) == day:
                    continue
                self._broken[(market_index, kind)] = day
                out.append(Fact(kind, direction, level, "px", size=1.0))
        return out

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
            spans: dict[int, float] = {}
            for span in SPANS:
                along: list[float] = []
                for mi in side:
                    ref = self._minute.ref_close(mi, span, now=now)
                    pct = _pct_change(self._snapshots[mi][-1].last, ref) if ref else None
                    if pct is not None:
                        along.append(pct)
                spans[span] = statistics.median(along) if along else 0.0
            broad = Broad(
                direction="up" if side is up else "down",
                move_5m=statistics.median(moves[mi] for mi in side),
                spans=spans,
                same=len(side),
                movers=movers,
                liquid=len(moves),
            )
        self._broad_cache = (now, broad)
        return broad

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
    "SPANS",
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
