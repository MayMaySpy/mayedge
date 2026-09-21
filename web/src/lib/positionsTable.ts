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

export type CloseFilter = "all" | "winners" | "losers";

/** Winners/losers use live uPnL; flats (0) only go through "all". */
export function positionsForClose<T extends { pnl: number }>(
  rows: T[],
  filter: CloseFilter
): T[] {
  if (filter === "winners") return rows.filter((r) => r.pnl > 0);
  if (filter === "losers") return rows.filter((r) => r.pnl < 0);
  return rows;
}

/** Full close is venue position-tied size 0. Partial is capped at the live position. */
export function protectCloseSize(
  posAbs: number,
  mode: "full" | "partial",
  qty: number
): number {
  if (mode === "full") return 0;
  if (!(posAbs > 0) || !(qty > 0)) return 0;
  return Math.min(qty, posAbs);
}

export function triggerOnCorrectSide(
  kind: "sl" | "tp",
  closeIsAsk: boolean,
  trigger: number,
  mark: number
): boolean {
  if (!(trigger > 0) || !(mark > 0)) return false;
  if (kind === "sl") return closeIsAsk ? trigger < mark : trigger > mark;
  return closeIsAsk ? trigger > mark : trigger < mark;
}

export function stopTakeKind(orderType: string): "sl" | "tp" | null {
  const t = orderType.toLowerCase().replace(/[_-\s]/g, "");
  if (t.includes("stoploss") || t === "2" || t === "3") return "sl";
  if (t.includes("takeprofit") || t === "4" || t === "5") return "tp";
  return null;
}

export function workingProtectOrders<
  T extends { market_index: number; order_type: string; trigger_price?: string },
>(orders: T[], marketIndex: number): T[] {
  return orders.filter(
    (o) => o.market_index === marketIndex && stopTakeKind(o.order_type) != null
  );
}

export function protectOrderLabel(orderType: string, triggerPrice: string | undefined): string {
  const kind = stopTakeKind(orderType);
  const tag = kind === "sl" ? "SL" : kind === "tp" ? "TP" : null;
  if (!tag) return orderType;
  const trig = (triggerPrice ?? "").trim();
  return trig ? `${tag} ${trig}` : tag;
}

export function protectTriggersFromOrders<
  T extends { order_type: string; trigger_price?: string },
>(orders: T[]): { tp?: string; sl?: string } {
  let tp: string | undefined;
  let sl: string | undefined;
  for (const o of orders) {
    const kind = stopTakeKind(o.order_type);
    const trig = (o.trigger_price ?? "").trim();
    if (!kind || !trig) continue;
    if (kind === "tp") tp = trig;
    else sl = trig;
  }
  return { tp, sl };
}

/** Lighter-style row: `tp / sl`, blanks as __. */
export function protectTriggersLabel(tp?: string, sl?: string): string {
  return `${(tp ?? "").trim() || "__"} / ${(sl ?? "").trim() || "__"}`;
}

/** PnL if the position were closed at trigger vs entry. */
export function pnlAtTrigger(entry: number, size: number, trigger: number): number | null {
  if (!(entry > 0) || !(trigger > 0) || size === 0 || !Number.isFinite(size)) return null;
  return (trigger - entry) * size;
}

export function triggerFromPnl(entry: number, size: number, pnl: number): number | null {
  if (!(entry > 0) || size === 0 || !Number.isFinite(size) || !Number.isFinite(pnl)) return null;
  const trigger = entry + pnl / size;
  return trigger > 0 ? trigger : null;
}

export function roeFromPnl(pnl: number, margin: number, notional: number): number | null {
  if (!Number.isFinite(pnl)) return null;
  if (margin > 0) return (pnl / margin) * 100;
  if (notional > 0) return (pnl / notional) * 100;
  return null;
}

export function pnlFromRoe(roe: number, margin: number, notional: number): number | null {
  if (!Number.isFinite(roe)) return null;
  if (margin > 0) return (roe / 100) * margin;
  if (notional > 0) return (roe / 100) * notional;
  return null;
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
