import type { PriceSample } from "@/lib/watchPath";

const WATCH_SAMPLE_CAP = 14_400;

const rings = new Map<string, PriceSample[]>();

export function getWatchSamples(symbol: string): PriceSample[] {
  return rings.get(symbol) ?? [];
}

export function clearWatchSamples() {
  rings.clear();
}

export function snapshotWatchSamples(): Record<string, PriceSample[]> {
  const out: Record<string, PriceSample[]> = {};
  for (const [symbol, series] of rings) {
    out[symbol] = series.map((s) => ({ t: s.t, px: s.px }));
  }
  return out;
}

export function replaceWatchSamples(next: Record<string, PriceSample[]>) {
  rings.clear();
  for (const [symbol, series] of Object.entries(next)) {
    if (!Array.isArray(series) || !symbol) continue;
    const copy: PriceSample[] = [];
    for (const s of series) {
      if (!s || !Number.isFinite(s.t) || !Number.isFinite(s.px) || !(s.px > 0)) continue;
      copy.push({ t: s.t, px: s.px });
    }
    if (copy.length) rings.set(symbol, copy);
  }
}

/** Append one Last per Watchlist Market at nowSec. Cap is 4h of 1s samples. */
export function rollWatch(
  symbols: readonly string[],
  lasts: Readonly<Record<string, number | null | undefined>>,
  nowSec: number,
  cap = WATCH_SAMPLE_CAP
) {
  const keep = new Set(symbols);
  for (const key of [...rings.keys()]) {
    if (!keep.has(key)) rings.delete(key);
  }
  for (const symbol of symbols) {
    const px = lasts[symbol];
    if (px == null || !Number.isFinite(px) || !(px > 0)) continue;
    let series = rings.get(symbol);
    if (!series) {
      series = [];
      rings.set(symbol, series);
    }
    const last = series[series.length - 1];
    if (last && last.t === nowSec) {
      last.px = px;
      continue;
    }
    series.push({ t: nowSec, px });
    if (series.length > cap) series.splice(0, series.length - cap);
  }
}
