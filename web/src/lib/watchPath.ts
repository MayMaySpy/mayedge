export type PriceSample = { t: number; px: number };
export type PathPoint = { t: number; pct: number };

/** Last for a Path sample: last trade, else mark, else mid. Missing is unknown, not 0. */
export function lastForWatch(m: {
  last_trade_price?: number | null;
  mark_price?: number | null;
  mid_price?: number | null;
}): number | null {
  const px = m.last_trade_price ?? m.mark_price ?? m.mid_price;
  if (px == null || !Number.isFinite(px) || !(px > 0)) return null;
  return px;
}

/** Rebase samples so the first valid Last at or after t0 is 0%. */
export function pathFromSamples(samples: readonly PriceSample[], t0: number): PathPoint[] {
  let px0: number | null = null;
  const out: PathPoint[] = [];
  for (const s of samples) {
    if (s.t < t0) continue;
    if (!Number.isFinite(s.px) || !(s.px > 0)) continue;
    if (px0 == null) px0 = s.px;
    out.push({ t: s.t, pct: roundPct((s.px / px0 - 1) * 100) });
  }
  return out;
}

function roundPct(n: number): number {
  return Math.round(n * 1e10) / 1e10;
}

export const WATCH_LINE_COLORS = [
  "#6ea8ff",
  "#c084fc",
  "#f0b429",
  "#2dd4bf",
  "#fb7185",
  "#a3e635",
  "#818cf8",
  "#f97316",
] as const;

export function watchLineColor(symbol: string, list: readonly string[]): string {
  const i = list.indexOf(symbol);
  const idx = i >= 0 ? i % WATCH_LINE_COLORS.length : 0;
  return WATCH_LINE_COLORS[idx];
}
