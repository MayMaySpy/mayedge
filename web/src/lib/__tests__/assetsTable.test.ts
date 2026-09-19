import { describe, expect, it } from "vitest";
import {
  assetChartSymbol,
  nextAssetSort,
  sortAssetRows,
  type SortableAsset,
} from "@/lib/assetsTable";

function row(symbol: string, opts: Partial<Omit<SortableAsset, "symbol">> = {}): SortableAsset {
  return { symbol, usd: 0, balance: 0, ...opts };
}

describe("assetChartSymbol", () => {
  const markets = [{ symbol: "ETH" }, { symbol: "BTC" }];

  it("returns the symbol when a Market is listed", () => {
    expect(assetChartSymbol("ETH", markets)).toBe("ETH");
  });

  it("returns null for quote holdings with no Market", () => {
    expect(assetChartSymbol("USDC", markets)).toBeNull();
  });
});

describe("sortAssetRows", () => {
  const rows = [
    row("USDC", { usd: 1362.84, balance: 1362.84 }),
    row("ETH", { usd: 2464.57, balance: 1 }),
  ];

  it("sorts by USD desc", () => {
    expect(sortAssetRows(rows, { key: "usd", dir: "desc" }).map((r) => r.symbol)).toEqual([
      "ETH",
      "USDC",
    ]);
  });

  it("sorts by balance desc", () => {
    expect(sortAssetRows(rows, { key: "balance", dir: "desc" }).map((r) => r.symbol)).toEqual([
      "USDC",
      "ETH",
    ]);
  });
});

describe("nextAssetSort", () => {
  it("defaults a new column to desc, then toggles", () => {
    expect(nextAssetSort({ key: "usd", dir: "desc" }, "balance")).toEqual({
      key: "balance",
      dir: "desc",
    });
    expect(nextAssetSort({ key: "balance", dir: "desc" }, "balance")).toEqual({
      key: "balance",
      dir: "asc",
    });
  });
});
