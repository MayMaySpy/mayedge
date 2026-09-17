export type LiqHeatSort = "total" | "long" | "short" | "net" | "share";
export type LiqHeatDir = "asc" | "desc";

export type LiquidationHeatInput = {
  symbol: string;
  market_index: number;
  long_usd: number;
  short_usd: number;
  total_usd: number;
  fill_count: number;
};

export type LiquidationHeatRow = {
  symbol: string;
  marketIndex: number;
  longUsd: number;
  shortUsd: number;
  totalUsd: number;
  fillCount: number;
  netUsd: number;
  openInterest: number | null;
  shareOfOi: number | null;
};

export type LiquidationWindowFold = {
  totalUsd: number;
  longUsd: number;
  shortUsd: number;
  marketCount: number;
  top: { symbol: string; totalUsd: number; share: number } | null;
};

export function foldLiquidationWindow(
  rows: readonly LiquidationHeatRow[]
): LiquidationWindowFold {
  let totalUsd = 0;
  let longUsd = 0;
  let shortUsd = 0;
  let top: LiquidationHeatRow | null = null;
  for (const row of rows) {
    totalUsd += row.totalUsd;
    longUsd += row.longUsd;
    shortUsd += row.shortUsd;
    if (
      top == null ||
      row.totalUsd > top.totalUsd ||
      (row.totalUsd === top.totalUsd && row.symbol.localeCompare(top.symbol) < 0)
    ) {
      top = row;
    }
  }
  return {
    totalUsd,
    longUsd,
    shortUsd,
    marketCount: rows.length,
    top:
      top && totalUsd > 0
        ? { symbol: top.symbol, totalUsd: top.totalUsd, share: top.totalUsd / totalUsd }
        : null,
  };
}

function lookupOi(
  symbol: string,
  openInterest: Readonly<Record<string, number>> | undefined
): number | null {
  if (!openInterest) return null;
  const v = openInterest[symbol.toUpperCase()];
  if (v == null || !Number.isFinite(v) || v <= 0) return null;
  return v;
}

function sortValue(row: LiquidationHeatRow, sort: LiqHeatSort): number | null {
  switch (sort) {
    case "total":
      return row.totalUsd;
    case "long":
      return row.longUsd;
    case "short":
      return row.shortUsd;
    case "net":
      return row.netUsd;
    case "share":
      return row.shareOfOi;
  }
}

function compareRows(
  a: LiquidationHeatRow,
  b: LiquidationHeatRow,
  sort: LiqHeatSort,
  dir: LiqHeatDir
): number {
  const av = sortValue(a, sort);
  const bv = sortValue(b, sort);
  if (av == null && bv == null) return a.symbol.localeCompare(b.symbol);
  if (av == null) return 1;
  if (bv == null) return -1;
  if (av === bv) return a.symbol.localeCompare(b.symbol);
  const sign = dir === "asc" ? 1 : -1;
  return (av < bv ? -1 : 1) * sign;
}

export function rankLiquidationHeat(
  rows: readonly LiquidationHeatInput[],
  options?: {
    sort?: LiqHeatSort;
    dir?: LiqHeatDir;
    openInterest?: Readonly<Record<string, number>>;
  }
): LiquidationHeatRow[] {
  const sort = options?.sort ?? "total";
  const dir = options?.dir ?? "desc";
  const mapped = rows
    .filter((r) => r.total_usd > 0)
    .map((r) => {
      const openInterest = lookupOi(r.symbol, options?.openInterest);
      return {
        symbol: r.symbol,
        marketIndex: r.market_index,
        longUsd: r.long_usd,
        shortUsd: r.short_usd,
        totalUsd: r.total_usd,
        fillCount: r.fill_count,
        netUsd: r.short_usd - r.long_usd,
        openInterest,
        shareOfOi: openInterest != null ? r.total_usd / openInterest : null,
      };
    });
  mapped.sort((a, b) => compareRows(a, b, sort, dir));
  return mapped;
}
