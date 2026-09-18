import { watchLineColor } from "@/lib/watchPath";

export type WatchChip = {
  symbol: string;
  color: string;
  pct: number | null;
};

/** Chips follow Watchlist add order. Path is display only. */
export function listWatchChips(
  symbols: readonly string[],
  pct: Readonly<Record<string, number | null | undefined>>
): WatchChip[] {
  return symbols.map((s) => ({
    symbol: s,
    color: watchLineColor(s, symbols),
    pct: pct[s] ?? null,
  }));
}
