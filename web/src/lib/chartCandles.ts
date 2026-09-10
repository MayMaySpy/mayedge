import type { CandlestickData, HistogramData, UTCTimestamp } from "lightweight-charts";
import type { Candle } from "@/lib/api";

const VOL_UP = "rgba(46, 204, 113, 0.55)";
const VOL_DOWN = "rgba(255, 77, 94, 0.55)";

/** LWC expects unique, strictly increasing unix seconds. */
export function candleTime(t: number): UTCTimestamp {
  const sec = t > 1e12 ? Math.floor(t / 1000) : Math.floor(t);
  return sec as UTCTimestamp;
}

export function formatBarVolume(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(abs >= 100_000 ? 0 : 1)}k`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export interface ChartSeriesData {
  candles: CandlestickData[];
  volume: HistogramData[];
}

/** Duplicate/non-monotonic times freeze lightweight-charts on setData. */
export function toSeriesData(candles: Candle[]): ChartSeriesData {
  const out: CandlestickData[] = [];
  const volume: HistogramData[] = [];
  let prevT = -Infinity;
  for (const c of candles) {
    const t = candleTime(c.time) as number;
    if (!Number.isFinite(t) || t <= 0) continue;
    if (
      !Number.isFinite(c.open) ||
      !Number.isFinite(c.high) ||
      !Number.isFinite(c.low) ||
      !Number.isFinite(c.close)
    ) {
      continue;
    }
    const bar: CandlestickData = {
      time: t as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    };
    const vol: HistogramData = {
      time: t as UTCTimestamp,
      value: Number.isFinite(c.volume) && c.volume > 0 ? c.volume : 0,
      color: c.close >= c.open ? VOL_UP : VOL_DOWN,
    };
    if (t === prevT && out.length) {
      out[out.length - 1] = bar;
      volume[volume.length - 1] = vol;
      continue;
    }
    if (t < prevT) continue;
    out.push(bar);
    volume.push(vol);
    prevT = t;
  }
  return { candles: out, volume };
}

const MAX_CHART_BARS = 2500;

/** REST history + live WS — live wins on the same timestamp. */
export function mergeCandles(hist: Candle[], live: Candle[]): Candle[] {
  if (!live.length) return hist.length > MAX_CHART_BARS ? hist.slice(-MAX_CHART_BARS) : hist;
  if (!hist.length) return live.length > MAX_CHART_BARS ? live.slice(-MAX_CHART_BARS) : live;
  const byT = new Map<number, Candle>();
  for (const c of hist) byT.set(candleTime(c.time) as number, { ...c, time: candleTime(c.time) as number });
  for (const c of live) byT.set(candleTime(c.time) as number, { ...c, time: candleTime(c.time) as number });
  const out = [...byT.values()].sort((a, b) => a.time - b.time);
  return out.length > MAX_CHART_BARS ? out.slice(-MAX_CHART_BARS) : out;
}

export function foldMinute(hist: Candle[], minute: Candle, tfSec: number): Candle[] {
  const mt = candleTime(minute.time) as number;
  const bucket = Math.floor(mt / tfSec) * tfSec;
  const vol = Number.isFinite(minute.volume) ? minute.volume : 0;
  if (!hist.length) {
    return [{ ...minute, time: bucket, volume: vol }];
  }
  const last = hist[hist.length - 1];
  const lastT = candleTime(last.time) as number;
  if (lastT === bucket) {
    return [
      ...hist.slice(0, -1),
      {
        time: bucket,
        open: last.open,
        high: Math.max(last.high, minute.high),
        low: Math.min(last.low, minute.low),
        close: minute.close,
        volume: (Number.isFinite(last.volume) ? last.volume : 0) + vol,
      },
    ];
  }
  if (bucket > lastT) {
    return [
      ...hist,
      {
        time: bucket,
        open: minute.open,
        high: minute.high,
        low: minute.low,
        close: minute.close,
        volume: vol,
      },
    ];
  }
  return hist;
}

/** Bucket 1m (or any finer) bars into `tfSec` candles. */
export function aggregateCandles(src: Candle[], tfSec: number): Candle[] {
  if (tfSec <= 0) return src;
  const out: Candle[] = [];
  for (const raw of src) {
    const t = candleTime(raw.time) as number;
    if (!Number.isFinite(t) || t <= 0) continue;
    const bucket = Math.floor(t / tfSec) * tfSec;
    const vol = Number.isFinite(raw.volume) ? raw.volume : 0;
    const last = out[out.length - 1];
    if (last && last.time === bucket) {
      last.high = Math.max(last.high, raw.high);
      last.low = Math.min(last.low, raw.low);
      last.close = raw.close;
      last.volume += vol;
      continue;
    }
    if (last && bucket < last.time) continue;
    out.push({
      time: bucket,
      open: raw.open,
      high: raw.high,
      low: raw.low,
      close: raw.close,
      volume: vol,
    });
  }
  return out;
}

/**
 * REST higher-tf history + all live 1m bars.
 * Overlapping last REST bucket is extended; newer buckets become new candles.
 */
export function foldMinutes(hist: Candle[], minutes: Candle[], tfSec: number): Candle[] {
  if (!minutes.length) return hist.length > MAX_CHART_BARS ? hist.slice(-MAX_CHART_BARS) : hist;
  const liveTf = aggregateCandles(minutes, tfSec);
  if (!hist.length) return liveTf.length > MAX_CHART_BARS ? liveTf.slice(-MAX_CHART_BARS) : liveTf;

  const last = hist[hist.length - 1];
  const lastT = candleTime(last.time) as number;
  let overlap: Candle | null = null;
  const newer: Candle[] = [];
  for (const b of liveTf) {
    const t = candleTime(b.time) as number;
    if (t === lastT) overlap = b;
    else if (t > lastT) newer.push(b);
  }

  let out = hist;
  if (overlap) {
    const histVol = Number.isFinite(last.volume) ? last.volume : 0;
    out = [
      ...hist.slice(0, -1),
      {
        time: lastT,
        open: last.open,
        high: Math.max(last.high, overlap.high),
        low: Math.min(last.low, overlap.low),
        close: overlap.close,
        volume: Math.max(histVol, overlap.volume),
      },
    ];
  }
  if (newer.length) out = [...out, ...newer];
  return out.length > MAX_CHART_BARS ? out.slice(-MAX_CHART_BARS) : out;
}

export interface ChartBarMeta {
  first: number;
  time: number;
  len: number;
}

/** Incremental LWC `update()` is only safe for same last time, or exactly one new bar. */
export function shouldReplaceChartData(
  prev: ChartBarMeta | null,
  next: ChartBarMeta,
  primed: boolean
): boolean {
  if (!primed || prev == null) return true;
  if (next.first !== prev.first) return true;
  if (next.len < prev.len) return true;
  if (next.time < prev.time) return true;
  if (next.len > prev.len + 1) return true;
  if (next.len === prev.len && next.time !== prev.time) return true;
  return false;
}
