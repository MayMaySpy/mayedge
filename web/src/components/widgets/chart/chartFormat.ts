import type { CandlestickData, ISeriesApi } from "lightweight-charts";

import type { Candle } from "@/lib/api";
import { formatPrice } from "@/lib/utils";

export type Ohlc = { open: number; high: number; low: number; close: number; volume?: number };

export function sameOhlc(a: Ohlc | null, b: Ohlc | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.open === b.open &&
    a.high === b.high &&
    a.low === b.low &&
    a.close === b.close &&
    a.volume === b.volume
  );
}

export function ohlcOf(
  c: Candle | CandlestickData | Ohlc | null | undefined,
  volume?: number,
): Ohlc | null {
  if (!c) return null;
  if (!Number.isFinite(c.open) || !Number.isFinite(c.close)) return null;
  const vol = volume ?? ("volume" in c && Number.isFinite(c.volume) ? c.volume : undefined);
  return { open: c.open, high: c.high, low: c.low, close: c.close, volume: vol };
}

/** The price axis, its labels and the chart's lines print prices as the rest of the desk does. */
export function priceFormat(decimals: number) {
  const d = Math.max(0, Math.min(8, Math.floor(decimals)));
  return {
    type: "custom" as const,
    minMove: d === 0 ? 1 : 10 ** -d,
    formatter: (price: number) => formatPrice(price, d),
  };
}

export function applyVolumeLayout(series: ISeriesApi<"Candlestick">, on: boolean) {
  series.priceScale().applyOptions({
    scaleMargins: { top: 0.08, bottom: on ? 0.22 : 0.08 },
  });
}
