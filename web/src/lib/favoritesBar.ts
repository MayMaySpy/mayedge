import type { Market } from "@/lib/api";
import { lastPrice } from "@/lib/marketPicker";
import { formatPrice } from "@/lib/utils";

export function favPriceLabel(m: Market): string {
  const n = lastPrice(m);
  if (!(n > 0)) return "—";
  return formatPrice(n, m.price_decimals ?? 4);
}

export function favChangeTone(change: number | null | undefined): "bid" | "ask" | "muted" {
  if (change == null || change === 0) return "muted";
  return change > 0 ? "bid" : "ask";
}

export function scrollFadeX(
  scrollLeft: number,
  clientWidth: number,
  scrollWidth: number,
  fade = 24
): { fadeL: number; fadeR: number; showRight: boolean } {
  const max = Math.max(0, scrollWidth - clientWidth);
  const overflow = max > 1;
  const atStart = scrollLeft <= 1;
  const atEnd = scrollLeft >= max - 1;
  return {
    fadeL: overflow && !atStart ? fade : 0,
    fadeR: overflow && !atEnd ? fade : 0,
    showRight: overflow && !atEnd,
  };
}

export type FavRect = { id: string; left: number; width: number };

/** Insert index among the chips that are not being dragged. */
export function insertIndexAtX(x: number, rects: FavRect[], draggingId: string): number {
  let i = 0;
  for (const r of rects) {
    if (r.id === draggingId) continue;
    if (x >= r.left + r.width / 2) i += 1;
  }
  return i;
}

export function moveIdToIndex(list: string[], id: string, to: number): string[] {
  const from = list.indexOf(id);
  if (from < 0) return list;
  const rest = list.filter((s) => s !== id);
  const idx = Math.max(0, Math.min(to, rest.length));
  if (from === idx) return list;
  return [...rest.slice(0, idx), id, ...rest.slice(idx)];
}
