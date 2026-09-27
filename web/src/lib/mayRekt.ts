import type { Candle } from "@/lib/api";

/** A candle's MayRekt color. Null means the bar keeps the desk bid/ask colors. */
export type Tone =
  | "breakout-strong"
  | "breakout-weak"
  | "breakdown-strong"
  | "breakdown-weak"
  | "ur"
  | "bon"
  | "ucru"
  | "uncrd"
  | "pivot"
  | "five-high-reject"
  | "uw-strong"
  | "uw-weak"
  | "up-strong"
  | "up-weak"
  | "down-strong"
  | "down-weak"
  | "neutral";

const SENSITIVITY = 1;
const BASE_TREND = 16;
const BASE_VOL = 14;
const BASE_MOMENTUM = 9;
const REGIME_PERIOD = 50;
const FAST_MA = 8;
const SLOW_MA = 21;
const STRUCTURE = 20;
const DIVERGENCE = 14;
const VELOCITY = 5;
const FIVE_BAR_OFFSET = 0.01;
const VOLUME_CONFIRM = 1.2;
const STRONG_TREND = 75;

function finite(n: number): boolean {
  return Number.isFinite(n);
}

function nz(n: number, repl = 0): number {
  return finite(n) ? n : repl;
}

function clamp(n: number, lo: number, hi: number): number {
  if (!finite(n)) return NaN;
  return Math.min(hi, Math.max(lo, n));
}

function gt(a: number, b: number): boolean {
  return finite(a) && finite(b) && a > b;
}

function lt(a: number, b: number): boolean {
  return finite(a) && finite(b) && a < b;
}

function lag(src: readonly number[], i: number, barsBack: number): number {
  const j = i - barsBack;
  return j >= 0 ? src[j] : NaN;
}

function sma(src: readonly number[], length: number): number[] {
  return src.map((_, i) => {
    if (length < 1 || i < length - 1) return NaN;
    let sum = 0;
    for (let k = 0; k < length; k++) {
      const v = src[i - k];
      if (!finite(v)) return NaN;
      sum += v;
    }
    return sum / length;
  });
}

function ema(src: readonly number[], length: number): number[] {
  const out = src.map(() => NaN);
  const alpha = 2 / (length + 1);
  let prev = NaN;
  let seed = 0;
  let seen = 0;
  for (let i = 0; i < src.length; i++) {
    const v = src[i];
    if (!finite(prev)) {
      if (!finite(v)) continue;
      seed += v;
      seen += 1;
      if (seen === length) {
        prev = seed / length;
        out[i] = prev;
      }
      continue;
    }
    if (!finite(v)) {
      out[i] = NaN;
      continue;
    }
    prev = alpha * v + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

function rma(src: readonly number[], length: number): number[] {
  const out = src.map(() => NaN);
  let prev = NaN;
  let seed = 0;
  let seen = 0;
  for (let i = 0; i < src.length; i++) {
    const v = src[i];
    if (!finite(prev)) {
      if (!finite(v)) continue;
      seed += v;
      seen += 1;
      if (seen === length) {
        prev = seed / length;
        out[i] = prev;
      }
      continue;
    }
    if (!finite(v)) {
      out[i] = NaN;
      continue;
    }
    prev = (prev * (length - 1) + v) / length;
    out[i] = prev;
  }
  return out;
}

function stdev(src: readonly number[], length: number): number[] {
  const mean = sma(src, length);
  return src.map((_, i) => {
    const avg = mean[i];
    if (!finite(avg)) return NaN;
    let acc = 0;
    for (let k = 0; k < length; k++) {
      const v = src[i - k];
      if (!finite(v)) return NaN;
      const d = v - avg;
      acc += d * d;
    }
    return Math.sqrt(acc / length);
  });
}

function change(src: readonly number[], length: number): number[] {
  return src.map((v, i) => {
    const prev = lag(src, i, length);
    return finite(v) && finite(prev) ? v - prev : NaN;
  });
}

function roc(src: readonly number[], length: number): number[] {
  return src.map((v, i) => {
    const prev = lag(src, i, length);
    if (!finite(v) || !finite(prev) || prev === 0) return NaN;
    return (100 * (v - prev)) / prev;
  });
}

function rolling(src: readonly number[], length: number, pick: "high" | "low"): number[] {
  return src.map((_, i) => {
    if (i < length - 1) return NaN;
    let best = pick === "high" ? -Infinity : Infinity;
    for (let k = 0; k < length; k++) {
      const v = src[i - k];
      if (!finite(v)) return NaN;
      if (pick === "high" ? v > best : v < best) best = v;
    }
    return best;
  });
}

/** highest(src[shift], length) — the window ends `shift` bars ago. */
function rollingShifted(
  src: readonly number[],
  shift: number,
  length: number,
  pick: "high" | "low"
): number[] {
  return src.map((_, i) => {
    const end = i - shift;
    const start = end - length + 1;
    if (start < 0) return NaN;
    let best = pick === "high" ? -Infinity : Infinity;
    for (let k = start; k <= end; k++) {
      const v = src[k];
      if (!finite(v)) return NaN;
      if (pick === "high" ? v > best : v < best) best = v;
    }
    return best;
  });
}

function trueRange(high: readonly number[], low: readonly number[], close: readonly number[]): number[] {
  return high.map((h, i) => {
    const span = h - low[i];
    if (i === 0) return span;
    const prev = close[i - 1];
    return Math.max(span, Math.abs(h - prev), Math.abs(low[i] - prev));
  });
}

function atr(high: readonly number[], low: readonly number[], close: readonly number[], length: number): number[] {
  return rma(trueRange(high, low, close), length);
}

function rsi(src: readonly number[], length: number): number[] {
  const gain = src.map(() => NaN);
  const loss = src.map(() => NaN);
  for (let i = 1; i < src.length; i++) {
    const delta = src[i] - src[i - 1];
    if (!finite(delta)) continue;
    gain[i] = Math.max(delta, 0);
    loss[i] = Math.max(-delta, 0);
  }
  const avgGain = rma(gain, length);
  const avgLoss = rma(loss, length);
  return src.map((_, i) => {
    const g = avgGain[i];
    const l = avgLoss[i];
    if (!finite(g) || !finite(l)) return NaN;
    if (l === 0) return g === 0 ? 50 : 100;
    return 100 - 100 / (1 + g / l);
  });
}

function macd(src: readonly number[]): { line: number[]; signal: number[] } {
  const fast = ema(src, 12);
  const slow = ema(src, 26);
  const line = src.map((_, i) =>
    finite(fast[i]) && finite(slow[i]) ? fast[i] - slow[i] : NaN
  );
  return { line, signal: ema(line, 9) };
}

function stoch(
  close: readonly number[],
  high: readonly number[],
  low: readonly number[],
  length: number
): number[] {
  const hh = rolling(high, length, "high");
  const ll = rolling(low, length, "low");
  return close.map((c, i) => {
    const top = hh[i];
    const bot = ll[i];
    if (!finite(top) || !finite(bot) || top === bot) return NaN;
    return (100 * (c - bot)) / (top - bot);
  });
}

function shift(src: readonly number[], barsBack: number): number[] {
  return src.map((_, i) => lag(src, i, barsBack));
}

function percentRank(src: readonly number[], length: number, i: number): number {
  if (!finite(length) || length < 1 || i < length) return NaN;
  const current = src[i];
  if (!finite(current)) return NaN;
  let count = 0;
  for (let k = 1; k <= length; k++) {
    const prev = src[i - k];
    if (!finite(prev)) return NaN;
    if (current > prev) count += 1;
  }
  return (100 * count) / length;
}

function adaptivePeriod(base: number, vol: number): number {
  if (!finite(vol) || vol <= 0) return base;
  const clampedVol = Math.min(3, Math.max(0.3, vol));
  const adjusted = Math.round(base * (2 - clampedVol) * SENSITIVITY);
  return Math.min(base * 2, Math.max(2, adjusted));
}

function adaptiveWeight(base: number, vol: number, regime: number): number {
  if (!finite(vol) || !finite(regime)) return NaN;
  return clamp(base * (1 + vol * 0.5 + regime * 0.5), 1.5, 4);
}

/** Pine's recursive average: seed with the rolling sum, then a weighted step. */
function adaptiveLine(
  src: readonly number[],
  basePeriod: number,
  baseWeight: number,
  vol: readonly number[],
  regime: readonly number[]
): number[] {
  const out = src.map(() => NaN);
  let sum = 0;
  let prev = NaN;
  for (let i = 0; i < src.length; i++) {
    const period = adaptivePeriod(basePeriod, vol[i]);
    const lagged = lag(src, i, period);
    sum = nz(sum) - nz(lagged) + src[i];
    const ma = finite(lagged) ? sum / period : NaN;
    if (!finite(prev)) {
      prev = ma;
      out[i] = prev;
      continue;
    }
    const weight = adaptiveWeight(baseWeight, vol[i], regime[i]) / (period + 1);
    prev = (src[i] - prev) * weight + prev;
    out[i] = prev;
  }
  return out;
}

function marketRegime(
  close: readonly number[],
  high: readonly number[],
  low: readonly number[]
): number[] {
  const half = Math.trunc(REGIME_PERIOD / 2);
  const quarter = Math.trunc(REGIME_PERIOD / 4);
  const atrP = atr(high, low, close, REGIME_PERIOD);
  const emaP = ema(close, REGIME_PERIOD);
  const breaks = close.map((c, i) => {
    if (!finite(emaP[i]) || !finite(atrP[i])) return NaN;
    const upper = emaP[i] + atrP[i];
    const lower = emaP[i] - atrP[i];
    return (c > upper ? 1 : 0) + (c < lower ? 1 : 0);
  });
  const breakoutRate = sma(breaks, REGIME_PERIOD);
  const normDM = change(ema(close, half), quarter).map((move, i) => {
    const span = atrP[i];
    if (!finite(move) || !finite(span) || span === 0) return NaN;
    return Math.abs(move) / span;
  });
  const delta = change(close, 1);
  const upShare = sma(
    delta.map((v) => (finite(v) ? (v > 0 ? 1 : 0) : NaN)),
    REGIME_PERIOD
  );
  const downShare = sma(
    delta.map((v) => (finite(v) ? (v < 0 ? 1 : 0) : NaN)),
    REGIME_PERIOD
  );
  const volNow = stdev(close, half);
  const volAvg = sma(volNow, REGIME_PERIOD);
  return close.map((_, i) => {
    const rate = breakoutRate[i];
    const dm = normDM[i];
    const up = upShare[i];
    const down = downShare[i];
    const now = volNow[i];
    const avg = volAvg[i];
    if (![rate, dm, up, down, now, avg].every(finite)) return NaN;
    // 0/0 is unchanged volatility. A flat close would otherwise leave the regime undefined.
    const persistence = avg === 0 ? (now === 0 ? 1 : Infinity) : now / avg;
    const score =
      rate * 0.3 +
      Math.min(dm, 1) * 0.3 +
      Math.abs(up - down) * 0.25 +
      (Math.min(persistence, 2) / 2) * 0.15;
    return clamp(score, 0, 1);
  });
}

function structureScore(high: readonly number[], low: readonly number[]): number[] {
  const recentHigh = rolling(high, STRUCTURE, "high");
  const recentLow = rolling(low, STRUCTURE, "low");
  const prevHigh = rollingShifted(high, STRUCTURE, STRUCTURE, "high");
  const prevLow = rollingShifted(low, STRUCTURE, STRUCTURE, "low");
  return high.map((_, i) => {
    const hh = gt(recentHigh[i], prevHigh[i]);
    const hl = gt(recentLow[i], prevLow[i]);
    const lh = lt(recentHigh[i], prevHigh[i]);
    const ll = lt(recentLow[i], prevLow[i]);
    if (hh && hl) return 1;
    if (lh && ll) return -1;
    if (hh || hl) return 0.5;
    if (lh || ll) return -0.5;
    return 0;
  });
}

function divergenceScore(close: readonly number[]): number[] {
  const priceDir = change(close, DIVERGENCE).map((v) => (gt(v, 0) ? 1 : lt(v, 0) ? -1 : 0));
  const rsiNow = rsi(close, 14);
  const rsiThen = rsi(shift(close, DIVERGENCE), 14);
  const macdNow = macd(close);
  const macdThen = macd(shift(close, DIVERGENCE));
  return close.map((_, i) => {
    const px = priceDir[i];
    const rsiMove = rsiNow[i] - rsiThen[i];
    const rsiDir = gt(rsiMove, 0) ? 1 : lt(rsiMove, 0) ? -1 : 0;
    const macdMove = macdNow.line[i] - macdThen.line[i];
    const macdDir = gt(macdMove, 0) ? 1 : lt(macdMove, 0) ? -1 : 0;
    const rsiDiv = px !== rsiDir && px !== 0 && rsiDir !== 0 ? -px : 0;
    const macdDiv = px !== macdDir && px !== 0 && macdDir !== 0 ? -px : 0;
    return clamp((rsiDiv + macdDiv) / 2, -1, 1);
  });
}

function signOf(fast: number, slow: number): number {
  if (gt(fast, slow)) return 1;
  if (lt(fast, slow)) return -1;
  return 0;
}

function trendDirection(
  close: readonly number[],
  highLine: readonly number[],
  lowLine: readonly number[],
  structure: readonly number[]
): number[] {
  const fast = ema(close, FAST_MA);
  const slow = ema(close, SLOW_MA);
  return close.map((c, i) => {
    const emaTrend = signOf(fast[i], slow[i]);
    if (gt(c, highLine[i]) && emaTrend > 0 && structure[i] > 0) return 1;
    if (lt(c, lowLine[i]) && emaTrend < 0 && structure[i] < 0) return -1;
    return 0;
  });
}

function volumeScore(
  close: readonly number[],
  volume: readonly number[],
  direction: readonly number[]
): number[] {
  const avg = sma(volume, 20);
  const delta = change(close, 1);
  const signed = volume.map((v, i) => {
    if (gt(delta[i], 0)) return v;
    if (lt(delta[i], 0)) return -v;
    return 0;
  });
  const obv: number[] = [];
  for (const v of signed) obv.push((obv[obv.length - 1] ?? 0) + v);
  const slope = change(ema(obv, 10), 1);
  return direction.map((dir, i) => {
    const mean = avg[i];
    const ratio = finite(mean) && mean !== 0 ? volume[i] / mean : NaN;
    const confirmsUp = gt(delta[i], 0) && gt(ratio, VOLUME_CONFIRM);
    const confirmsDown = lt(delta[i], 0) && gt(ratio, VOLUME_CONFIRM);
    if (dir > 0) return confirmsUp ? 0.8 : gt(slope[i], 0) ? 0.7 : 0.4;
    if (dir < 0) return confirmsDown ? 0.8 : lt(slope[i], 0) ? 0.7 : 0.4;
    return 0.5;
  });
}

function momentumScore(
  close: readonly number[],
  high: readonly number[],
  low: readonly number[],
  direction: readonly number[]
): number[] {
  const rsiLine = rsi(close, BASE_MOMENTUM);
  const macdLine = macd(close);
  const atrLine = atr(high, low, close, BASE_MOMENTUM);
  const velocity = roc(close, VELOCITY).map((v, i) => {
    const span = atrLine[i];
    return finite(v) && finite(span) && span !== 0 ? v / span : NaN;
  });
  const accel = change(velocity, 3);
  const stochLine = stoch(close, high, low, BASE_MOMENTUM);
  return direction.map((dir, i) => {
    if (dir === 0) return 0.5;
    const rsiMomentum = (rsiLine[i] - 50) / 50;
    const rsiWithVelocity = rsiMomentum + nz(velocity[i]) * 0.3;
    const macdMomentum = gt(macdLine.line[i], macdLine.signal[i]) ? 1 : -1;
    const macdWithAccel = macdMomentum + nz(accel[i]) * 0.2;
    const stochMomentum = (stochLine[i] - 50) / 50;
    if (![rsiWithVelocity, macdWithAccel, stochMomentum].every(finite)) return NaN;
    const combined = rsiWithVelocity * 0.4 + macdWithAccel * 0.4 + stochMomentum * 0.2;
    const aligned = (dir > 0 && combined > 0) || (dir < 0 && combined < 0);
    return aligned ? Math.min(1, 0.5 + Math.abs(combined)) : Math.max(0, 0.5 - Math.abs(combined));
  });
}

function strength(
  rank: number,
  momentum: number,
  regime: number,
  structure: number,
  divergence: number,
  volume: number,
  vol: number
): number {
  if (![rank, momentum, regime, structure, divergence, volume, vol].every(finite)) return NaN;
  const volAdj = vol > 1.5 ? -15 : vol < 0.5 ? 10 : 0;
  const raw =
    rank +
    (momentum - 0.5) * 60 +
    (regime - 0.5) * 30 +
    structure * 20 +
    (divergence < 0 ? divergence * 25 : divergence * 5) +
    (volume - 0.5) * 20 +
    volAdj;
  return clamp(raw, 0, 100);
}

function toneOf(
  bo: boolean,
  bd: boolean,
  ur: boolean,
  bon: boolean,
  ucru: boolean,
  uncrd: boolean,
  pivot: boolean,
  five: boolean,
  uw: boolean,
  up: boolean,
  down: boolean,
  neutral: boolean,
  strongUp: boolean,
  strongDown: boolean
): Tone | null {
  if (bo) return strongUp ? "breakout-strong" : "breakout-weak";
  if (bd) return strongDown ? "breakdown-strong" : "breakdown-weak";
  if (ur) return "ur";
  if (bon) return "bon";
  if (ucru) return "ucru";
  if (uncrd) return "uncrd";
  if (pivot) return "pivot";
  if (five) return "five-high-reject";
  if (uw) return strongUp ? "uw-strong" : "uw-weak";
  if (up) return strongUp ? "up-strong" : "up-weak";
  if (down) return strongDown ? "down-strong" : "down-weak";
  if (neutral) return "neutral";
  return null;
}

/** One tone per bar, aligned with `bars`. Null when the bar has no state. */
export function candleTones(bars: readonly Candle[]): (Tone | null)[] {
  const n = bars.length;
  if (n === 0) return [];
  const open = bars.map((b) => b.open);
  const high = bars.map((b) => b.high);
  const low = bars.map((b) => b.low);
  const close = bars.map((b) => b.close);
  const volume = bars.map((b) => b.volume);

  const atr14 = atr(high, low, close, BASE_VOL);
  const atrAvg = sma(atr14, BASE_VOL * 2);
  const vol = atr14.map((span, i) => {
    const mean = atrAvg[i];
    if (!finite(mean) || mean <= 0) return 1;
    return span / mean;
  });
  const regime = marketRegime(close, high, low);
  const structure = structureScore(high, low);
  const divergence = divergenceScore(close);
  const lowStandard = adaptiveLine(low, BASE_TREND, 2, vol, regime);
  const lowEnhanced = adaptiveLine(low, BASE_TREND, 3.5, vol, regime);
  const highStandard = adaptiveLine(high, BASE_TREND, 2, vol, regime);
  const highEnhanced = adaptiveLine(high, BASE_TREND, 3.5, vol, regime);
  const direction = trendDirection(close, highStandard, lowStandard, structure);
  const volumeConf = volumeScore(close, volume, direction);
  const momentum = momentumScore(close, high, low, direction);

  const lowDiff = lowStandard.map((v, i) => v - lowEnhanced[i]);
  const highDiff = highEnhanced.map((v, i) => v - highStandard[i]);
  const rankPeriod = vol.map((v) => adaptivePeriod(8, v));

  const currentHigh = high.map(() => NaN);
  const currentLow = low.map(() => NaN);
  const lowStrength = low.map(() => NaN);
  const highStrength = high.map(() => NaN);
  for (let i = 0; i < n; i++) {
    const trending = gt(regime[i], 0.6);
    const lowCut = trending ? (gt(vol[i], 1.5) ? 75 : 70) : 80;
    const highCut = trending ? (gt(vol[i], 1.5) ? 25 : 30) : 20;
    lowStrength[i] = strength(
      percentRank(lowDiff, rankPeriod[i], i),
      momentum[i],
      regime[i],
      structure[i],
      divergence[i],
      volumeConf[i],
      vol[i]
    );
    highStrength[i] = strength(
      100 - percentRank(highDiff, rankPeriod[i], i),
      momentum[i],
      regime[i],
      structure[i],
      divergence[i],
      volumeConf[i],
      vol[i]
    );
    const lowStrong = lt(lowDiff[i], 0) && gt(lowStrength[i], lowCut);
    const highStrong = gt(highDiff[i], 0) && gt(highStrength[i], highCut);
    currentHigh[i] = highStrong ? highStandard[i] : highEnhanced[i];
    currentLow[i] = lowStrong ? lowStandard[i] : lowEnhanced[i];
  }

  const low2 = rolling(low, 2, "low");
  const low3 = rolling(low, 3, "low");
  const high3 = rolling(high, 3, "high");

  return close.map((c, i) => {
    const o = open[i];
    const h = high[i];
    const l = low[i];
    const c1 = lag(close, i, 1);
    const c2 = lag(close, i, 2);
    const c3 = lag(close, i, 3);
    const c4 = lag(close, i, 4);
    const c5 = lag(close, i, 5);
    const o1 = lag(open, i, 1);
    const h1 = lag(high, i, 1);
    const l1 = lag(low, i, 1);
    const l2 = lag(low, i, 2);
    const ch = currentHigh[i];
    const cl = currentLow[i];
    const ph1 = lag(currentHigh, i, 1);
    const ph2 = lag(currentHigh, i, 2);
    const ph3 = lag(currentHigh, i, 3);
    const ph4 = lag(currentHigh, i, 4);
    const pl1 = lag(currentLow, i, 1);
    const pl2 = lag(currentLow, i, 2);
    const pl3 = lag(currentLow, i, 3);
    const pl4 = lag(currentLow, i, 4);
    const pl5 = lag(currentLow, i, 5);
    const hs = highStandard[i];
    const ls = lowStandard[i];
    const min1 = lag(low2, i, 1);
    const min2 = lag(low2, i, 2);
    const min3 = lag(low3, i, 1);
    const max3 = lag(high3, i, 1);
    const max3b = lag(high3, i, 2);

    const bo = lt(c3, pl3) && lt(c2, pl2) && lt(c1, pl1) && gt(c, ch);
    const bd = gt(c3, ph3) && gt(c2, ph2) && gt(c1, ph1) && lt(c, cl);
    const ur = gt(c2, ph2) && lt(c, c1) && lt(c, ch) && gt(c, min3) && lt(c, o) && lt(c, l1);
    const bon =
      (lt(c4, pl4) && lt(c3, pl3) && lt(c2, pl2) && gt(c1, ph1) && gt(c, min1) && lt(c, h1)) ||
      (lt(c5, pl5) &&
        lt(c4, pl4) &&
        lt(c3, pl3) &&
        gt(c2, ph2) &&
        lt(c, ch) &&
        gt(c1, min2) &&
        gt(c, min1) &&
        lt(c, h1) &&
        gt(o, c));
    const ucru = lt(c1, pl1) && gt(c, cl) && lt(c, ch) && gt(c, o);
    const uncrd =
      (gt(c2, pl2) && lt(l1, pl1) && lt(c1, pl1) && lt(h, h1) && lt(c, cl) && gt(l, l1) && gt(c, c1)) ||
      (gt(l2, pl2) && lt(l1, pl1) && gt(c1, pl1) && gt(c, l1) && lt(c, cl)) ||
      (gt(c2, pl2) && lt(c1, pl2) && gt(l1, l2) && (gt(c, l1) || gt(c, l2)) && gt(l, l2) && lt(c, cl));
    const pivot =
      (lt(c1, ph1) &&
        gt(c2, pl2) &&
        lt(l1, pl1) &&
        gt(c1, pl1) &&
        lt(h, h1) &&
        gt(h, cl) &&
        (lt(c, cl) || lt(c, c1)) &&
        gt(c, l1) &&
        lt(o, c)) ||
      (gt(c4, ph4) && gt(c, ch) && lt(c3, pl3) && gt(c1, ph1) && lt(c1, max3b) && gt(o, c) && gt(c, l1));
    const five = gt(h, max3 + FIVE_BAR_OFFSET) && lt(c, o) && gt(c1, ph1) && gt(c1, o1) && gt(c, cl);
    const uw = lt(c1, ph1) && gt(c, hs) && lt(c, h1);
    const up = gt(c, hs);
    const down = lt(c, ls);
    const neutral = (gt(c, ls) && lt(c, hs)) || (gt(c, hs) && lt(c1, ls));

    const upPower = up ? Math.max(lowStrength[i], highStrength[i]) : 0;
    const downPower = down ? Math.max(lowStrength[i], highStrength[i]) : 0;
    const strongCut = gt(regime[i], 0.6) ? STRONG_TREND : STRONG_TREND + 10;
    const strongUp = gt(upPower, strongCut) && structure[i] > 0 && gt(momentum[i], 0.6);
    const strongDown = gt(downPower, strongCut) && structure[i] < 0 && gt(momentum[i], 0.6);

    return toneOf(bo, bd, ur, bon, ucru, uncrd, pivot, five, uw, up, down, neutral, strongUp, strongDown);
  });
}

export interface TonePaint {
  color: string;
  borderColor: string;
  wickColor: string;
}

/** Body, border, and wick share one color so the candle reads as a single tone. */
const TONE_COLOR: Record<Tone, string> = {
  "breakout-strong": "rgb(253, 216, 53)",
  "breakout-weak": "rgba(253, 216, 53, 0.7)",
  "breakdown-strong": "rgb(156, 39, 176)",
  "breakdown-weak": "rgba(156, 39, 176, 0.7)",
  ur: "rgb(255, 152, 0)",
  bon: "rgb(128, 128, 0)",
  ucru: "rgb(0, 102, 255)",
  uncrd: "rgb(255, 0, 255)",
  pivot: "rgb(255, 0, 255)",
  "five-high-reject": "rgb(117, 138, 10)",
  "uw-strong": "rgb(76, 175, 80)",
  "uw-weak": "rgba(76, 175, 80, 0.7)",
  "up-strong": "rgb(0, 230, 118)",
  "up-weak": "rgba(0, 230, 118, 0.7)",
  "down-strong": "rgb(242, 54, 69)",
  "down-weak": "rgba(242, 54, 69, 0.7)",
  neutral: "rgb(159, 180, 180)",
};

export function tonePaint(tone: Tone): TonePaint {
  const color = TONE_COLOR[tone];
  return { color, borderColor: color, wickColor: color };
}
