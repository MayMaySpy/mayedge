export type PosSortKey = "size" | "notional" | "pnl" | "roe";
export type PosSortDir = "asc" | "desc";
export type PosSort = { key: PosSortKey; dir: PosSortDir };

export function positionNotional(size: number, mark: number, entry = 0): number {
  const px = mark > 0 ? mark : entry;
  if (!(px > 0) || !Number.isFinite(size)) return 0;
  return Math.abs(size) * px;
}

export function nextPosSort(current: PosSort, key: PosSortKey): PosSort {
  if (current.key === key) {
    return { key, dir: current.dir === "desc" ? "asc" : "desc" };
  }
  return { key, dir: "desc" };
}

export type SortablePosition = {
  marketIndex: number;
  sizeAbs: number;
  notional: number;
  pnl: number;
  roe: number | null;
};

function sortValue(row: SortablePosition, key: PosSortKey): number | null {
  switch (key) {
    case "size":
      return row.sizeAbs;
    case "notional":
      return row.notional;
    case "pnl":
      return row.pnl;
    case "roe":
      return row.roe;
  }
}

/** Active market stays first; remaining rows follow the selected numeric sort. */
export function sortPositionRows<T extends SortablePosition>(
  rows: T[],
  sort: PosSort,
  activeMarketIndex: number | null
): T[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const aActive = activeMarketIndex != null && a.marketIndex === activeMarketIndex;
    const bActive = activeMarketIndex != null && b.marketIndex === activeMarketIndex;
    if (aActive !== bActive) return aActive ? -1 : 1;
    const av = sortValue(a, sort.key);
    const bv = sortValue(b, sort.key);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (av === bv) return 0;
    return (av < bv ? -1 : 1) * sign;
  });
}
