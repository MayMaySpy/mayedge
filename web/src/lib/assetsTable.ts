export type AssetSortKey = "usd" | "balance";
export type AssetSortDir = "asc" | "desc";
export type AssetSort = { key: AssetSortKey; dir: AssetSortDir };

export type SortableAsset = {
  symbol: string;
  usd: number;
  balance: number;
};

/** Switch the chart only when the Asset shares a listed Market symbol. */
export function assetChartSymbol(
  symbol: string,
  markets: { symbol: string }[]
): string | null {
  return markets.some((m) => m.symbol === symbol) ? symbol : null;
}

export function nextAssetSort(current: AssetSort, key: AssetSortKey): AssetSort {
  if (current.key === key) {
    return { key, dir: current.dir === "desc" ? "asc" : "desc" };
  }
  return { key, dir: "desc" };
}

function sortValue(row: SortableAsset, key: AssetSortKey): number {
  return key === "usd" ? row.usd : row.balance;
}

export function sortAssetRows<T extends SortableAsset>(rows: T[], sort: AssetSort): T[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = sortValue(a, sort.key);
    const bv = sortValue(b, sort.key);
    if (av === bv) return 0;
    return (av < bv ? -1 : 1) * sign;
  });
}
