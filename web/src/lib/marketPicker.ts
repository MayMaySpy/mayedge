import type { Market } from "@/lib/api";

export type PickerTab = "all" | "favorites";
export type PickerSort = "symbol" | "last" | "change" | "volume" | "oi" | "funding";
export type SortDir = "asc" | "desc";

export function lastPrice(m: Market): number {
  return m.last_trade_price ?? m.mark_price ?? m.mid_price ?? 0;
}

export function filterPickerMarkets(
  markets: Market[],
  query: string,
  tab: PickerTab,
  favorites: readonly string[]
): Market[] {
  const q = query.trim().toUpperCase();
  const fav = new Set(favorites);
  return markets.filter((m) => {
    if (tab === "favorites" && !fav.has(m.symbol)) return false;
    if (!q) return true;
    return m.symbol.toUpperCase().includes(q);
  });
}

function sortValue(m: Market, sort: PickerSort): number | string {
  switch (sort) {
    case "symbol":
      return m.symbol;
    case "last":
      return lastPrice(m);
    case "change":
      return m.change_24h ?? Number.NEGATIVE_INFINITY;
    case "volume":
      return m.volume_24h ?? 0;
    case "oi":
      return m.open_interest ?? 0;
    case "funding":
      return m.funding_rate ?? Number.NEGATIVE_INFINITY;
  }
}

export function sortPickerMarkets(markets: Market[], sort: PickerSort, dir: SortDir): Market[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...markets].sort((a, b) => {
    const av = sortValue(a, sort);
    const bv = sortValue(b, sort);
    if (typeof av === "string" && typeof bv === "string") {
      return av.localeCompare(bv) * sign;
    }
    const an = Number(av);
    const bn = Number(bv);
    if (an === bn) return a.symbol.localeCompare(b.symbol);
    return (an < bn ? -1 : 1) * sign;
  });
}

/** Lighter 1h funding is already a percent (0.0012 → +0.0012%/hr). */
export function formatFundingPct(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return "—";
  const sign = rate > 0 ? "+" : "";
  return `${sign}${rate.toFixed(4)}%`;
}

export function tokenIconUrl(symbol: string): string {
  const slug = symbol.toLowerCase().replace(/[^a-z0-9]/g, "");
  return `https://assets.lighter.xyz/fe/token/${slug}.png`;
}
