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

/** REST history + live WS — live wins on the same timestamp. */
export function mergeCandles(hist: Candle[], live: Candle[]): Candle[] {
  if (!live.length) return hist;
  if (!hist.length) return live;
  const byT = new Map<number, Candle>();
  for (const c of hist) byT.set(candleTime(c.time) as number, { ...c, time: candleTime(c.time) as number });
  for (const c of live) byT.set(candleTime(c.time) as number, { ...c, time: candleTime(c.time) as number });
  return [...byT.values()].sort((a, b) => a.time - b.time);
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
