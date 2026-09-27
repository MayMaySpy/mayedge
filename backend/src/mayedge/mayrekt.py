"""MayRekt tones. Same rules as the chart's candleTones."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

_NAN = math.nan

_SENSITIVITY = 1
_BASE_TREND = 16
_BASE_VOL = 14
_BASE_MOMENTUM = 9
_REGIME_PERIOD = 50
_FAST_MA = 8
_SLOW_MA = 21
_STRUCTURE = 20
_DIVERGENCE = 14
_VELOCITY = 5
_FIVE_BAR_OFFSET = 0.01
_VOLUME_CONFIRM = 1.2
_STRONG_TREND = 75


class Bar(Protocol):
    open: float
    high: float
    low: float
    close: float
    volume: float


def _finite(n: float) -> bool:
    return math.isfinite(n)


def _nz(n: float, repl: float = 0.0) -> float:
    return n if _finite(n) else repl


def _clamp(n: float, lo: float, hi: float) -> float:
    if not _finite(n):
        return _NAN
    return min(hi, max(lo, n))


def _gt(a: float, b: float) -> bool:
    return _finite(a) and _finite(b) and a > b


def _lt(a: float, b: float) -> bool:
    return _finite(a) and _finite(b) and a < b


def _js_round(n: float) -> int:
    if n >= 0:
        return math.floor(n + 0.5)
    return math.ceil(n - 0.5)


def _js_max(*vals: float) -> float:
    best = vals[0]
    for v in vals[1:]:
        if not _finite(best) or not _finite(v):
            best = _NAN
            continue
        if v > best:
            best = v
    return best


def _lag(src: Sequence[float], i: int, bars_back: int) -> float:
    j = i - bars_back
    if j < 0:
        return _NAN
    return src[j]


def _sma(src: Sequence[float], length: int) -> list[float]:
    out: list[float] = []
    for i in range(len(src)):
        if length < 1 or i < length - 1:
            out.append(_NAN)
            continue
        total = 0.0
        bad = False
        for k in range(length):
            v = src[i - k]
            if not _finite(v):
                bad = True
                break
            total += v
        out.append(_NAN if bad else total / length)
    return out


def _ema(src: Sequence[float], length: int) -> list[float]:
    out = [_NAN] * len(src)
    alpha = 2 / (length + 1)
    prev = _NAN
    seed = 0.0
    seen = 0
    for i, v in enumerate(src):
        if not _finite(prev):
            if not _finite(v):
                continue
            seed += v
            seen += 1
            if seen == length:
                prev = seed / length
                out[i] = prev
            continue
        if not _finite(v):
            out[i] = _NAN
            continue
        prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def _rma(src: Sequence[float], length: int) -> list[float]:
    out = [_NAN] * len(src)
    prev = _NAN
    seed = 0.0
    seen = 0
    for i, v in enumerate(src):
        if not _finite(prev):
            if not _finite(v):
                continue
            seed += v
            seen += 1
            if seen == length:
                prev = seed / length
                out[i] = prev
            continue
        if not _finite(v):
            out[i] = _NAN
            continue
        prev = (prev * (length - 1) + v) / length
        out[i] = prev
    return out


def _stdev(src: Sequence[float], length: int) -> list[float]:
    mean = _sma(src, length)
    out: list[float] = []
    for i, avg in enumerate(mean):
        if not _finite(avg):
            out.append(_NAN)
            continue
        acc = 0.0
        bad = False
        for k in range(length):
            v = src[i - k]
            if not _finite(v):
                bad = True
                break
            d = v - avg
            acc += d * d
        out.append(_NAN if bad else math.sqrt(acc / length))
    return out


def _change(src: Sequence[float], length: int) -> list[float]:
    out: list[float] = []
    for i, v in enumerate(src):
        prev = _lag(src, i, length)
        out.append(v - prev if _finite(v) and _finite(prev) else _NAN)
    return out


def _roc(src: Sequence[float], length: int) -> list[float]:
    out: list[float] = []
    for i, v in enumerate(src):
        prev = _lag(src, i, length)
        if not _finite(v) or not _finite(prev) or prev == 0:
            out.append(_NAN)
        else:
            out.append((100 * (v - prev)) / prev)
    return out


def _rolling(src: Sequence[float], length: int, pick: str) -> list[float]:
    out: list[float] = []
    for i in range(len(src)):
        if i < length - 1:
            out.append(_NAN)
            continue
        best = -math.inf if pick == "high" else math.inf
        bad = False
        for k in range(length):
            v = src[i - k]
            if not _finite(v):
                bad = True
                break
            if pick == "high":
                if v > best:
                    best = v
            elif v < best:
                best = v
        out.append(_NAN if bad else best)
    return out


def _rolling_shifted(src: Sequence[float], shift: int, length: int, pick: str) -> list[float]:
    out: list[float] = []
    for i in range(len(src)):
        end = i - shift
        start = end - length + 1
        if start < 0:
            out.append(_NAN)
            continue
        best = -math.inf if pick == "high" else math.inf
        bad = False
        for k in range(start, end + 1):
            v = src[k]
            if not _finite(v):
                bad = True
                break
            if pick == "high":
                if v > best:
                    best = v
            elif v < best:
                best = v
        out.append(_NAN if bad else best)
    return out


def _true_range(high: Sequence[float], low: Sequence[float], close: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i, h in enumerate(high):
        span = h - low[i]
        if i == 0:
            out.append(span)
            continue
        prev = close[i - 1]
        out.append(_js_max(span, abs(h - prev), abs(low[i] - prev)))
    return out


def _atr(
    high: Sequence[float], low: Sequence[float], close: Sequence[float], length: int
) -> list[float]:
    return _rma(_true_range(high, low, close), length)


def _rsi(src: Sequence[float], length: int) -> list[float]:
    gain = [_NAN] * len(src)
    loss = [_NAN] * len(src)
    for i in range(1, len(src)):
        delta = src[i] - src[i - 1]
        if not _finite(delta):
            continue
        gain[i] = max(delta, 0.0)
        loss[i] = max(-delta, 0.0)
    avg_gain = _rma(gain, length)
    avg_loss = _rma(loss, length)
    out: list[float] = []
    for i in range(len(src)):
        g = avg_gain[i]
        ell = avg_loss[i]
        if not _finite(g) or not _finite(ell):
            out.append(_NAN)
        elif ell == 0:
            out.append(50.0 if g == 0 else 100.0)
        else:
            out.append(100 - 100 / (1 + g / ell))
    return out


def _macd(src: Sequence[float]) -> tuple[list[float], list[float]]:
    fast = _ema(src, 12)
    slow = _ema(src, 26)
    line = [
        fast[i] - slow[i] if _finite(fast[i]) and _finite(slow[i]) else _NAN
        for i in range(len(src))
    ]
    return line, _ema(line, 9)


def _stoch(
    close: Sequence[float], high: Sequence[float], low: Sequence[float], length: int
) -> list[float]:
    hh = _rolling(high, length, "high")
    ll = _rolling(low, length, "low")
    out: list[float] = []
    for i, c in enumerate(close):
        top = hh[i]
        bot = ll[i]
        if not _finite(top) or not _finite(bot) or top == bot:
            out.append(_NAN)
        else:
            out.append((100 * (c - bot)) / (top - bot))
    return out


def _shift(src: Sequence[float], bars_back: int) -> list[float]:
    return [_lag(src, i, bars_back) for i in range(len(src))]


def _percent_rank(src: Sequence[float], length: int, i: int) -> float:
    if length < 1 or i < length:
        return _NAN
    current = src[i]
    if not _finite(current):
        return _NAN
    count = 0
    for k in range(1, length + 1):
        prev = src[i - k]
        if not _finite(prev):
            return _NAN
        if current > prev:
            count += 1
    return (100 * count) / length


def _adaptive_period(base: int, vol: float) -> int:
    if not _finite(vol) or vol <= 0:
        return base
    clamped_vol = min(3.0, max(0.3, vol))
    adjusted = _js_round(base * (2 - clamped_vol) * _SENSITIVITY)
    return min(base * 2, max(2, adjusted))


def _adaptive_weight(base: float, vol: float, regime: float) -> float:
    if not _finite(vol) or not _finite(regime):
        return _NAN
    return _clamp(base * (1 + vol * 0.5 + regime * 0.5), 1.5, 4)


def _adaptive_line(
    src: Sequence[float],
    base_period: int,
    base_weight: float,
    vol: Sequence[float],
    regime: Sequence[float],
) -> list[float]:
    out = [_NAN] * len(src)
    total = 0.0
    prev = _NAN
    for i, value in enumerate(src):
        period = _adaptive_period(base_period, vol[i])
        lagged = _lag(src, i, period)
        total = _nz(total) - _nz(lagged) + value
        ma = total / period if _finite(lagged) else _NAN
        if not _finite(prev):
            prev = ma
            out[i] = prev
            continue
        weight = _adaptive_weight(base_weight, vol[i], regime[i]) / (period + 1)
        prev = (value - prev) * weight + prev
        out[i] = prev
    return out


def _market_regime(
    close: Sequence[float], high: Sequence[float], low: Sequence[float]
) -> list[float]:
    half = _REGIME_PERIOD // 2
    quarter = _REGIME_PERIOD // 4
    atr_p = _atr(high, low, close, _REGIME_PERIOD)
    ema_p = _ema(close, _REGIME_PERIOD)
    breaks: list[float] = []
    for i, c in enumerate(close):
        if not _finite(ema_p[i]) or not _finite(atr_p[i]):
            breaks.append(_NAN)
            continue
        upper = ema_p[i] + atr_p[i]
        lower = ema_p[i] - atr_p[i]
        breaks.append((1 if c > upper else 0) + (1 if c < lower else 0))
    breakout_rate = _sma(breaks, _REGIME_PERIOD)
    ema_half = _ema(close, half)
    norm_dm: list[float] = []
    for i, move in enumerate(_change(ema_half, quarter)):
        span = atr_p[i]
        if not _finite(move) or not _finite(span) or span == 0:
            norm_dm.append(_NAN)
        else:
            norm_dm.append(abs(move) / span)
    delta = _change(close, 1)
    up_share = _sma(
        [1.0 if _finite(v) and v > 0 else (0.0 if _finite(v) else _NAN) for v in delta],
        _REGIME_PERIOD,
    )
    down_share = _sma(
        [1.0 if _finite(v) and v < 0 else (0.0 if _finite(v) else _NAN) for v in delta],
        _REGIME_PERIOD,
    )
    vol_now = _stdev(close, half)
    vol_avg = _sma(vol_now, _REGIME_PERIOD)
    out: list[float] = []
    for i in range(len(close)):
        parts = (
            breakout_rate[i],
            norm_dm[i],
            up_share[i],
            down_share[i],
            vol_now[i],
            vol_avg[i],
        )
        if not all(_finite(part) for part in parts):
            out.append(_NAN)
            continue
        rate, dm, up, down, now, avg = parts
        if avg == 0:
            persistence = 1.0 if now == 0 else math.inf
        else:
            persistence = now / avg
        if not all(_finite(part) for part in (rate, dm, up, down, persistence)):
            out.append(_NAN)
            continue
        score = (
            rate * 0.3 + min(dm, 1) * 0.3 + abs(up - down) * 0.25 + (min(persistence, 2) / 2) * 0.15
        )
        out.append(_clamp(score, 0, 1))
    return out


def _structure_score(high: Sequence[float], low: Sequence[float]) -> list[float]:
    recent_high = _rolling(high, _STRUCTURE, "high")
    recent_low = _rolling(low, _STRUCTURE, "low")
    prev_high = _rolling_shifted(high, _STRUCTURE, _STRUCTURE, "high")
    prev_low = _rolling_shifted(low, _STRUCTURE, _STRUCTURE, "low")
    out: list[float] = []
    for i in range(len(high)):
        hh = _gt(recent_high[i], prev_high[i])
        hl = _gt(recent_low[i], prev_low[i])
        lh = _lt(recent_high[i], prev_high[i])
        ll = _lt(recent_low[i], prev_low[i])
        if hh and hl:
            out.append(1)
        elif lh and ll:
            out.append(-1)
        elif hh or hl:
            out.append(0.5)
        elif lh or ll:
            out.append(-0.5)
        else:
            out.append(0)
    return out


def _sign_of(fast: float, slow: float) -> int:
    if _gt(fast, slow):
        return 1
    if _lt(fast, slow):
        return -1
    return 0


def _divergence_score(close: Sequence[float]) -> list[float]:
    price_dir = [1 if _gt(v, 0) else (-1 if _lt(v, 0) else 0) for v in _change(close, _DIVERGENCE)]
    rsi_now = _rsi(close, 14)
    rsi_then = _rsi(_shift(close, _DIVERGENCE), 14)
    macd_now, _signal_now = _macd(close)
    macd_then, _signal_then = _macd(_shift(close, _DIVERGENCE))
    out: list[float] = []
    for i, px in enumerate(price_dir):
        rsi_move = rsi_now[i] - rsi_then[i]
        rsi_dir = 1 if _gt(rsi_move, 0) else (-1 if _lt(rsi_move, 0) else 0)
        macd_move = macd_now[i] - macd_then[i]
        macd_dir = 1 if _gt(macd_move, 0) else (-1 if _lt(macd_move, 0) else 0)
        rsi_div = -px if px != rsi_dir and px != 0 and rsi_dir != 0 else 0
        macd_div = -px if px != macd_dir and px != 0 and macd_dir != 0 else 0
        out.append(_clamp((rsi_div + macd_div) / 2, -1, 1))
    return out


def _trend_direction(
    close: Sequence[float],
    high_line: Sequence[float],
    low_line: Sequence[float],
    structure: Sequence[float],
) -> list[float]:
    fast = _ema(close, _FAST_MA)
    slow = _ema(close, _SLOW_MA)
    out: list[float] = []
    for i, c in enumerate(close):
        ema_trend = _sign_of(fast[i], slow[i])
        if _gt(c, high_line[i]) and ema_trend > 0 and structure[i] > 0:
            out.append(1)
        elif _lt(c, low_line[i]) and ema_trend < 0 and structure[i] < 0:
            out.append(-1)
        else:
            out.append(0)
    return out


def _volume_score(
    close: Sequence[float], volume: Sequence[float], direction: Sequence[float]
) -> list[float]:
    avg = _sma(volume, 20)
    delta = _change(close, 1)
    signed: list[float] = []
    for i, v in enumerate(volume):
        if _gt(delta[i], 0):
            signed.append(v)
        elif _lt(delta[i], 0):
            signed.append(-v)
        else:
            signed.append(0)
    obv: list[float] = []
    running = 0.0
    for v in signed:
        running += v
        obv.append(running)
    slope = _change(_ema(obv, 10), 1)
    out: list[float] = []
    for i, dirn in enumerate(direction):
        mean = avg[i]
        ratio = volume[i] / mean if _finite(mean) and mean != 0 else _NAN
        confirms_up = _gt(delta[i], 0) and _gt(ratio, _VOLUME_CONFIRM)
        confirms_down = _lt(delta[i], 0) and _gt(ratio, _VOLUME_CONFIRM)
        if dirn > 0:
            out.append(0.8 if confirms_up else (0.7 if _gt(slope[i], 0) else 0.4))
        elif dirn < 0:
            out.append(0.8 if confirms_down else (0.7 if _lt(slope[i], 0) else 0.4))
        else:
            out.append(0.5)
    return out


def _momentum_score(
    close: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    direction: Sequence[float],
) -> list[float]:
    rsi_line = _rsi(close, _BASE_MOMENTUM)
    macd_line, macd_signal = _macd(close)
    atr_line = _atr(high, low, close, _BASE_MOMENTUM)
    roc_line = _roc(close, _VELOCITY)
    velocity = [
        roc_line[i] / atr_line[i]
        if _finite(roc_line[i]) and _finite(atr_line[i]) and atr_line[i] != 0
        else _NAN
        for i in range(len(close))
    ]
    accel = _change(velocity, 3)
    stoch_line = _stoch(close, high, low, _BASE_MOMENTUM)
    out: list[float] = []
    for i, dirn in enumerate(direction):
        if dirn == 0:
            out.append(0.5)
            continue
        rsi_momentum = (rsi_line[i] - 50) / 50
        rsi_with_velocity = rsi_momentum + _nz(velocity[i]) * 0.3
        macd_momentum = 1 if _gt(macd_line[i], macd_signal[i]) else -1
        macd_with_accel = macd_momentum + _nz(accel[i]) * 0.2
        stoch_momentum = (stoch_line[i] - 50) / 50
        if not all(_finite(part) for part in (rsi_with_velocity, macd_with_accel, stoch_momentum)):
            out.append(_NAN)
            continue
        combined = rsi_with_velocity * 0.4 + macd_with_accel * 0.4 + stoch_momentum * 0.2
        aligned = (dirn > 0 and combined > 0) or (dirn < 0 and combined < 0)
        if aligned:
            out.append(min(1, 0.5 + abs(combined)))
        else:
            out.append(max(0, 0.5 - abs(combined)))
    return out


def _strength(
    rank: float,
    momentum: float,
    regime: float,
    structure: float,
    divergence: float,
    volume: float,
    vol: float,
) -> float:
    if not all(
        _finite(part) for part in (rank, momentum, regime, structure, divergence, volume, vol)
    ):
        return _NAN
    if vol > 1.5:
        vol_adj = -15
    elif vol < 0.5:
        vol_adj = 10
    else:
        vol_adj = 0
    raw = (
        rank
        + (momentum - 0.5) * 60
        + (regime - 0.5) * 30
        + structure * 20
        + (divergence * 25 if divergence < 0 else divergence * 5)
        + (volume - 0.5) * 20
        + vol_adj
    )
    return _clamp(raw, 0, 100)


def _tone_of(
    bo: bool,
    bd: bool,
    ur: bool,
    bon: bool,
    ucru: bool,
    uncrd: bool,
    pivot: bool,
    five: bool,
    uw: bool,
    up: bool,
    down: bool,
    neutral: bool,
    strong_up: bool,
    strong_down: bool,
) -> str | None:
    if bo:
        return "breakout-strong" if strong_up else "breakout-weak"
    if bd:
        return "breakdown-strong" if strong_down else "breakdown-weak"
    if ur:
        return "ur"
    if bon:
        return "bon"
    if ucru:
        return "ucru"
    if uncrd:
        return "uncrd"
    if pivot:
        return "pivot"
    if five:
        return "five-high-reject"
    if uw:
        return "uw-strong" if strong_up else "uw-weak"
    if up:
        return "up-strong" if strong_up else "up-weak"
    if down:
        return "down-strong" if strong_down else "down-weak"
    if neutral:
        return "neutral"
    return None


def candle_tones(bars: Sequence[Bar]) -> list[str | None]:
    """One tone per bar. None when the bar has no state."""
    n = len(bars)
    if n == 0:
        return []
    open_ = [b.open for b in bars]
    high = [b.high for b in bars]
    low = [b.low for b in bars]
    close = [b.close for b in bars]
    volume = [b.volume for b in bars]

    atr14 = _atr(high, low, close, _BASE_VOL)
    atr_avg = _sma(atr14, _BASE_VOL * 2)
    vol: list[float] = []
    for i, span in enumerate(atr14):
        mean = atr_avg[i]
        if not _finite(mean) or mean <= 0:
            vol.append(1)
        else:
            vol.append(span / mean)
    regime = _market_regime(close, high, low)
    structure = _structure_score(high, low)
    divergence = _divergence_score(close)
    low_standard = _adaptive_line(low, _BASE_TREND, 2, vol, regime)
    low_enhanced = _adaptive_line(low, _BASE_TREND, 3.5, vol, regime)
    high_standard = _adaptive_line(high, _BASE_TREND, 2, vol, regime)
    high_enhanced = _adaptive_line(high, _BASE_TREND, 3.5, vol, regime)
    direction = _trend_direction(close, high_standard, low_standard, structure)
    volume_conf = _volume_score(close, volume, direction)
    momentum = _momentum_score(close, high, low, direction)

    low_diff = [low_standard[i] - low_enhanced[i] for i in range(n)]
    high_diff = [high_enhanced[i] - high_standard[i] for i in range(n)]
    rank_period = [_adaptive_period(8, v) for v in vol]

    current_high = [_NAN] * n
    current_low = [_NAN] * n
    low_strength = [_NAN] * n
    high_strength = [_NAN] * n
    for i in range(n):
        trending = _gt(regime[i], 0.6)
        if trending:
            low_cut = 75 if _gt(vol[i], 1.5) else 70
            high_cut = 25 if _gt(vol[i], 1.5) else 30
        else:
            low_cut = 80
            high_cut = 20
        low_strength[i] = _strength(
            _percent_rank(low_diff, rank_period[i], i),
            momentum[i],
            regime[i],
            structure[i],
            divergence[i],
            volume_conf[i],
            vol[i],
        )
        high_strength[i] = _strength(
            100 - _percent_rank(high_diff, rank_period[i], i),
            momentum[i],
            regime[i],
            structure[i],
            divergence[i],
            volume_conf[i],
            vol[i],
        )
        low_strong = _lt(low_diff[i], 0) and _gt(low_strength[i], low_cut)
        high_strong = _gt(high_diff[i], 0) and _gt(high_strength[i], high_cut)
        current_high[i] = high_standard[i] if high_strong else high_enhanced[i]
        current_low[i] = low_standard[i] if low_strong else low_enhanced[i]

    low2 = _rolling(low, 2, "low")
    low3 = _rolling(low, 3, "low")
    high3 = _rolling(high, 3, "high")

    tones: list[str | None] = []
    for i, c in enumerate(close):
        o = open_[i]
        h = high[i]
        ell = low[i]
        c1 = _lag(close, i, 1)
        c2 = _lag(close, i, 2)
        c3 = _lag(close, i, 3)
        c4 = _lag(close, i, 4)
        c5 = _lag(close, i, 5)
        o1 = _lag(open_, i, 1)
        h1 = _lag(high, i, 1)
        l1 = _lag(low, i, 1)
        l2 = _lag(low, i, 2)
        ch = current_high[i]
        cl = current_low[i]
        ph1 = _lag(current_high, i, 1)
        ph2 = _lag(current_high, i, 2)
        ph3 = _lag(current_high, i, 3)
        ph4 = _lag(current_high, i, 4)
        pl1 = _lag(current_low, i, 1)
        pl2 = _lag(current_low, i, 2)
        pl3 = _lag(current_low, i, 3)
        pl4 = _lag(current_low, i, 4)
        pl5 = _lag(current_low, i, 5)
        hs = high_standard[i]
        ls = low_standard[i]
        min1 = _lag(low2, i, 1)
        min2 = _lag(low2, i, 2)
        min3 = _lag(low3, i, 1)
        max3 = _lag(high3, i, 1)
        max3b = _lag(high3, i, 2)

        bo = _lt(c3, pl3) and _lt(c2, pl2) and _lt(c1, pl1) and _gt(c, ch)
        bd = _gt(c3, ph3) and _gt(c2, ph2) and _gt(c1, ph1) and _lt(c, cl)
        ur = (
            _gt(c2, ph2) and _lt(c, c1) and _lt(c, ch) and _gt(c, min3) and _lt(c, o) and _lt(c, l1)
        )
        bon = (
            _lt(c4, pl4)
            and _lt(c3, pl3)
            and _lt(c2, pl2)
            and _gt(c1, ph1)
            and _gt(c, min1)
            and _lt(c, h1)
        ) or (
            _lt(c5, pl5)
            and _lt(c4, pl4)
            and _lt(c3, pl3)
            and _gt(c2, ph2)
            and _lt(c, ch)
            and _gt(c1, min2)
            and _gt(c, min1)
            and _lt(c, h1)
            and _gt(o, c)
        )
        ucru = _lt(c1, pl1) and _gt(c, cl) and _lt(c, ch) and _gt(c, o)
        uncrd = (
            (
                _gt(c2, pl2)
                and _lt(l1, pl1)
                and _lt(c1, pl1)
                and _lt(h, h1)
                and _lt(c, cl)
                and _gt(ell, l1)
                and _gt(c, c1)
            )
            or (_gt(l2, pl2) and _lt(l1, pl1) and _gt(c1, pl1) and _gt(c, l1) and _lt(c, cl))
            or (
                _gt(c2, pl2)
                and _lt(c1, pl2)
                and _gt(l1, l2)
                and (_gt(c, l1) or _gt(c, l2))
                and _gt(ell, l2)
                and _lt(c, cl)
            )
        )
        pivot = (
            _lt(c1, ph1)
            and _gt(c2, pl2)
            and _lt(l1, pl1)
            and _gt(c1, pl1)
            and _lt(h, h1)
            and _gt(h, cl)
            and (_lt(c, cl) or _lt(c, c1))
            and _gt(c, l1)
            and _lt(o, c)
        ) or (
            _gt(c4, ph4)
            and _gt(c, ch)
            and _lt(c3, pl3)
            and _gt(c1, ph1)
            and _lt(c1, max3b)
            and _gt(o, c)
            and _gt(c, l1)
        )
        five = (
            _gt(h, max3 + _FIVE_BAR_OFFSET)
            and _lt(c, o)
            and _gt(c1, ph1)
            and _gt(c1, o1)
            and _gt(c, cl)
        )
        uw = _lt(c1, ph1) and _gt(c, hs) and _lt(c, h1)
        up = _gt(c, hs)
        down = _lt(c, ls)
        neutral = (_gt(c, ls) and _lt(c, hs)) or (_gt(c, hs) and _lt(c1, ls))

        up_power = _js_max(low_strength[i], high_strength[i]) if up else 0.0
        down_power = _js_max(low_strength[i], high_strength[i]) if down else 0.0
        strong_cut = _STRONG_TREND if _gt(regime[i], 0.6) else _STRONG_TREND + 10
        strong_up = _gt(up_power, strong_cut) and structure[i] > 0 and _gt(momentum[i], 0.6)
        strong_down = _gt(down_power, strong_cut) and structure[i] < 0 and _gt(momentum[i], 0.6)
        tones.append(
            _tone_of(
                bo,
                bd,
                ur,
                bon,
                ucru,
                uncrd,
                pivot,
                five,
                uw,
                up,
                down,
                neutral,
                strong_up,
                strong_down,
            )
        )
    return tones
