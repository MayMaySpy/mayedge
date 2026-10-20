import type { CandlestickData } from "lightweight-charts";

import type { Candle } from "@/lib/api";
import { candleTime } from "@/lib/chartCandles";
import { candleTones, tonePaint } from "@/lib/mayRekt";

export const INDICATOR_STRETCH = 0.28;

const TONE_STAMP_MS = 500;

function toneColors(bar: CandlestickData): Pick<CandlestickData, "color" | "borderColor" | "wickColor"> | null {
  if (!bar.color) return null;
  return { color: bar.color, borderColor: bar.borderColor, wickColor: bar.wickColor };
}

/** Reuse a recent full stamp while the forming bar's price updates. */
export function reuseToneStamp(
  prev: CandlestickData[] | null,
  rawBars: CandlestickData[],
  stampedAt: number,
  now: number
): CandlestickData[] | null {
  if (!prev || prev.length === 0 || now - stampedAt >= TONE_STAMP_MS) return null;
  if (prev.length !== rawBars.length || prev[0].time !== rawBars[0].time) return null;
  const lastPrev = prev[prev.length - 1];
  const lastRaw = rawBars[rawBars.length - 1];
  if (lastPrev.time !== lastRaw.time) return null;
  const next = prev.slice();
  const paint = toneColors(lastPrev);
  next[next.length - 1] = paint ? { ...lastRaw, ...paint } : lastRaw;
  return next;
}

export function stampMayRekt(bars: CandlestickData[], source: Candle[]): CandlestickData[] {
  const tones = candleTones(source);
  const byTime = new Map<number, { color: string; borderColor: string; wickColor: string }>();
  source.forEach((bar, i) => {
    const tone = tones[i];
    if (!tone) return;
    byTime.set(candleTime(bar.time) as number, tonePaint(tone));
  });
  return bars.map((bar) => {
    const paint = byTime.get(bar.time as number);
    if (!paint) return bar;
    return { ...bar, color: paint.color, borderColor: paint.borderColor, wickColor: paint.wickColor };
  });
}
