import { compareSortValues } from "@/lib/tableSort";
import type { ScanActivityRow, ToneBoardRow } from "@/lib/api";

export type ActivitySort = "share" | "volume" | "oi" | "funding" | "premium";
export type ActivitySortDir = "asc" | "desc";

export const ACTIVITY_SORTS: readonly ActivitySort[] = ["share", "volume", "oi", "funding", "premium"];

/** How far from normal the cell is. A cell with no baseline yet is unknown, not zero. */
export function activityValue(row: ScanActivityRow, sort: ActivitySort): number | null {
  switch (sort) {
    case "share":
      return row.share;
    case "volume":
      return row.vol_x;
    case "oi":
      return row.oi_5m == null ? null : Math.abs(row.oi_5m);
    case "funding":
      return row.funding_z == null ? null : Math.abs(row.funding_z);
    case "premium":
      return row.premium_z == null ? null : Math.abs(row.premium_z);
  }
}

export function rankActivity(
  rows: readonly ScanActivityRow[],
  sort: ActivitySort,
  dir: ActivitySortDir = "desc"
): ScanActivityRow[] {
  return [...rows].sort((a, b) =>
    compareSortValues(a, b, activityValue(a, sort), activityValue(b, sort), dir)
  );
}

export type ToneCell = { tone: "blue" | "orange"; closedAt: number };
export type ToneGridRow = { symbol: string; marketIndex: number; cells: Record<string, ToneCell> };

/** One line per market, one cell per Tone timeframe. Newest close first. */
export function toneGrid(rows: readonly ToneBoardRow[]): ToneGridRow[] {
  const byMarket = new Map<number, ToneGridRow>();
  for (const row of rows) {
    let line = byMarket.get(row.market_index);
    if (!line) {
      line = { symbol: row.symbol, marketIndex: row.market_index, cells: {} };
      byMarket.set(row.market_index, line);
    }
    line.cells[row.timeframe] = { tone: row.tone, closedAt: row.closed_at };
  }
  const newest = (line: ToneGridRow) => Math.max(...Object.values(line.cells).map((c) => c.closedAt));
  return [...byMarket.values()].sort(
    (a, b) => newest(b) - newest(a) || a.symbol.localeCompare(b.symbol)
  );
}
