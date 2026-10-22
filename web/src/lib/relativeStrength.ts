import { compareSortValues } from "@/lib/tableSort";
import { uniqueSymbolMarkets } from "@/lib/algos";
import type { Market } from "@/lib/api";

export type RsSort = "rs" | "volume" | "oi";
export type RsSortDir = "asc" | "desc";

export type RelativeStrengthRow = {
  symbol: string;
  marketIndex: number;
  change24h: number | null;
  relativeStrength: number | null;
  volume24h: number;
  openInterest: number;
  fundingRate: number | null;
  isNumeraire: boolean;
};

export type RelativeStrengthBoard = {
  numeraireSymbol: string;
  numeraireChange24h: number | null;
  rows: RelativeStrengthRow[];
};

const DEFAULT_NUMERAIRE = "BTC";

function dailyChange(m: Market | undefined): number | null {
  const v = m?.change_24h;
  if (v == null || Number.isNaN(v)) return null;
  return v;
}

function excessReturn(coin: number | null, numeraire: number | null): number | null {
  if (coin == null || numeraire == null) return null;
  return coin - numeraire;
}

function sortValue(row: RelativeStrengthRow, sort: RsSort): number | null {
  switch (sort) {
    case "rs":
      return row.relativeStrength;
    case "volume":
      return row.volume24h;
    case "oi":
      return row.openInterest;
  }
}

export function rankRelativeStrength(
  markets: readonly Market[],
  options?: {
    numeraireSymbol?: string;
    sort?: RsSort;
    dir?: RsSortDir;
  }
): RelativeStrengthBoard {
  const numeraireSymbol = (options?.numeraireSymbol ?? DEFAULT_NUMERAIRE).toUpperCase();
  const universe = uniqueSymbolMarkets([...markets]);
  const numeraire = universe.find((m) => m.symbol.toUpperCase() === numeraireSymbol);
  const numeraireChange24h = dailyChange(numeraire);

  const rows: RelativeStrengthRow[] = universe.map((m) => {
    const change24h = dailyChange(m);
    const isNumeraire = m.symbol.toUpperCase() === numeraireSymbol;
    return {
      symbol: m.symbol,
      marketIndex: m.market_index,
      change24h,
      relativeStrength: excessReturn(change24h, numeraireChange24h),
      volume24h: m.volume_24h ?? 0,
      openInterest: m.open_interest ?? 0,
      fundingRate: m.funding_rate ?? null,
      isNumeraire,
    };
  });

  const sort = options?.sort ?? "rs";
  const dir = options?.dir ?? "desc";
  rows.sort((a, b) => compareSortValues(a, b, sortValue(a, sort), sortValue(b, sort), dir));

  return { numeraireSymbol, numeraireChange24h, rows };
}
