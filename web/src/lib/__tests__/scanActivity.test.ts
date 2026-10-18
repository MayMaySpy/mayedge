import { describe, expect, it } from "vitest";
import type { ScanActivityRow, ToneBoardRow } from "@/lib/api";
import { rankActivity, toneGrid } from "@/lib/scanActivity";

function row(symbol: string, extra: Partial<ScanActivityRow> = {}): ScanActivityRow {
  return {
    market_index: symbol.charCodeAt(0),
    symbol,
    move_5m: 0,
    share: 0,
    day_range: 3,
    vol_x: 1,
    vol_usd_5m: 0,
    oi_5m: 0,
    oi_usd_5m: 0,
    funding: 0,
    funding_z: 0,
    premium: 0,
    premium_z: 0,
    held: false,
    ...extra,
  };
}

describe("rankActivity", () => {
  it("ranks by how far from normal, whichever way", () => {
    const rows = [
      row("A", { oi_5m: 0.4, funding_z: 1.0 }),
      row("B", { oi_5m: -2.1, funding_z: -4.2 }),
      row("C", { oi_5m: 1.0, funding_z: 2.0 }),
    ];
    expect(rankActivity(rows, "oi").map((r) => r.symbol)).toEqual(["B", "C", "A"]);
    expect(rankActivity(rows, "funding").map((r) => r.symbol)).toEqual(["B", "C", "A"]);
    expect(rankActivity(rows, "funding", "asc").map((r) => r.symbol)).toEqual(["A", "C", "B"]);
  });

  it("puts a cell with no baseline last, not at zero", () => {
    const rows = [row("A", { vol_x: null }), row("B", { vol_x: 0.2 }), row("C", { vol_x: 6 })];
    expect(rankActivity(rows, "volume").map((r) => r.symbol)).toEqual(["C", "B", "A"]);
    expect(rankActivity(rows, "volume", "asc").map((r) => r.symbol)).toEqual(["B", "C", "A"]);
  });
});

describe("toneGrid", () => {
  it("is one line per market with a cell per timeframe, newest close first", () => {
    const tone = (symbol: string, timeframe: string, closed_at: number, t: "blue" | "orange"): ToneBoardRow => ({
      market_index: symbol.charCodeAt(0),
      symbol,
      timeframe,
      tone: t,
      closed_at,
      close: 1,
    });
    const grid = toneGrid([
      tone("ETH", "4h", 100, "orange"),
      tone("SOL", "30m", 300, "blue"),
      tone("ETH", "30m", 200, "blue"),
    ]);
    expect(grid.map((r) => r.symbol)).toEqual(["SOL", "ETH"]);
    expect(grid[1].cells).toEqual({
      "4h": { tone: "orange", closedAt: 100 },
      "30m": { tone: "blue", closedAt: 200 },
    });
  });
});
