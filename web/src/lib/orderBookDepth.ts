export interface BookLevel {
  price: string;
  size: string;
}

export interface DepthRow {
  price: string;
  size: number;
  total: number;
}

export function toDepthRows(levels: BookLevel[], depth: number): DepthRow[] {
  const rows: DepthRow[] = [];
  let total = 0;
  for (let i = 0; i < levels.length && rows.length < depth; i++) {
    const size = parseFloat(levels[i].size) || 0;
    if (size <= 0) continue;
    total += size;
    rows.push({ price: levels[i].price, size, total });
  }
  return rows;
}

/** Cumulative bar as % of the side's max total; size bar as % of that row's total. */
export function depthBarWidths(
  size: number,
  total: number,
  maxTotal: number
): { cumPct: number; sizePct: number } {
  if (!(maxTotal > 0) || !(total > 0) || !(size > 0)) return { cumPct: 0, sizePct: 0 };
  return {
    cumPct: (total / maxTotal) * 100,
    sizePct: (size / total) * 100,
  };
}

export function sideMaxTotal(rows: DepthRow[]): number {
  return rows.at(-1)?.total ?? 0;
}

function num(value: string | number): number {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

export interface NotionalWalk {
  filledUsd: number;
  filledSize: number;
  avgPrice: number;
  worstPrice: number;
  complete: boolean;
  lastIndex: number;
  lastFrac: number;
}

/** Walk a side from the best level until `usd` is filled (or the book runs out). */
export function walkNotional(
  levels: { price: string | number; size: string | number }[],
  usd: number
): NotionalWalk | null {
  if (!(usd > 0) || levels.length === 0) return null;

  let remaining = usd;
  let filledUsd = 0;
  let filledSize = 0;
  let worstPrice = 0;
  let lastIndex = -1;
  let lastFrac = 0;

  for (let i = 0; i < levels.length; i++) {
    const price = num(levels[i].price);
    const size = num(levels[i].size);
    if (!(price > 0) || !(size > 0)) continue;
    const levelUsd = price * size;
    lastIndex = i;
    worstPrice = price;
    if (levelUsd >= remaining) {
      const take = remaining / price;
      filledSize += take;
      filledUsd += remaining;
      lastFrac = take / size;
      remaining = 0;
      break;
    }
    filledSize += size;
    filledUsd += levelUsd;
    lastFrac = 1;
    remaining -= levelUsd;
  }

  if (!(filledSize > 0)) return null;
  return {
    filledUsd,
    filledSize,
    avgPrice: filledUsd / filledSize,
    worstPrice,
    complete: remaining <= 1e-9,
    lastIndex,
    lastFrac,
  };
}

/** Worst-fill move vs mid, in percent. Null when the walk cannot fill. */
export function walkMovePct(walk: NotionalWalk | null, mid: number): number | null {
  if (!walk?.complete || !(mid > 0) || !(walk.worstPrice > 0)) return null;
  return ((walk.worstPrice - mid) / mid) * 100;
}
