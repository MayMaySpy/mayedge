import { describe, expect, it } from "vitest";
import {
  foldLiquidationWindow,
  rankLiquidationHeat,
  type LiquidationHeatInput,
} from "../liquidationHeat";

function r(partial: Partial<LiquidationHeatInput> & { symbol: string }): LiquidationHeatInput {
  return {
    market_index: 1,
    long_usd: 0,
    short_usd: 0,
    total_usd: 0,
    fill_count: 0,
    ...partial,
  };
}

describe("rankLiquidationHeat", () => {
  it("nets short USD minus long USD", () => {
    const rows = rankLiquidationHeat([
      r({
        symbol: "ETH",
        market_index: 1,
        long_usd: 6000,
        short_usd: 1000,
        total_usd: 7000,
        fill_count: 3,
      }),
    ]);
    expect(rows).toEqual([
      {
        symbol: "ETH",
        marketIndex: 1,
        longUsd: 6000,
        shortUsd: 1000,
        totalUsd: 7000,
        fillCount: 3,
        largestUsd: 0,
        windowShare: 1,
        netUsd: -5000,
        openInterest: null,
        shareOfOi: null,
      },
    ]);
  });

  it("sorts total USD descending by default", () => {
    const rows = rankLiquidationHeat([
      r({ symbol: "BTC", market_index: 2, short_usd: 5000, total_usd: 5000, fill_count: 1 }),
      r({
        symbol: "ETH",
        market_index: 1,
        long_usd: 6000,
        short_usd: 1000,
        total_usd: 7000,
        fill_count: 3,
      }),
    ]);
    expect(rows.map((x) => x.symbol)).toEqual(["ETH", "BTC"]);
    expect(rows.map((x) => x.totalUsd)).toEqual([7000, 5000]);
  });

  it("sorts net so short-heavy markets lead when descending", () => {
    const rows = rankLiquidationHeat(
      [
        r({ symbol: "ETH", market_index: 1, long_usd: 6000, total_usd: 6000, fill_count: 1 }),
        r({ symbol: "BTC", market_index: 2, short_usd: 5000, total_usd: 5000, fill_count: 1 }),
      ],
      { sort: "net", dir: "desc" }
    );
    expect(rows.map((x) => x.symbol)).toEqual(["BTC", "ETH"]);
    expect(rows.map((x) => x.netUsd)).toEqual([5000, -6000]);
  });

  it("sorts long USD descending", () => {
    const rows = rankLiquidationHeat(
      [
        r({ symbol: "BTC", market_index: 2, long_usd: 100, total_usd: 100, fill_count: 1 }),
        r({ symbol: "ETH", market_index: 1, long_usd: 900, total_usd: 900, fill_count: 1 }),
      ],
      { sort: "long", dir: "desc" }
    );
    expect(rows.map((x) => x.symbol)).toEqual(["ETH", "BTC"]);
  });

  it("omits markets with no notional", () => {
    const rows = rankLiquidationHeat([
      r({ symbol: "SOL", market_index: 3, total_usd: 0, fill_count: 0 }),
      r({ symbol: "ETH", market_index: 1, long_usd: 10, total_usd: 10, fill_count: 1 }),
    ]);
    expect(rows.map((x) => x.symbol)).toEqual(["ETH"]);
  });
});

describe("foldLiquidationWindow", () => {
  it("sums the window and names the largest Market's share of Window total", () => {
    const rows = rankLiquidationHeat([
      r({ symbol: "ETH", market_index: 1, long_usd: 8000, total_usd: 8000, fill_count: 2 }),
      r({ symbol: "BTC", market_index: 2, short_usd: 2000, total_usd: 2000, fill_count: 1 }),
    ]);
    expect(foldLiquidationWindow(rows)).toEqual({
      totalUsd: 10000,
      longUsd: 8000,
      shortUsd: 2000,
      largestUsd: 0,
      marketCount: 2,
      top: { symbol: "ETH", totalUsd: 8000, share: 0.8 },
    });
  });

  it("is empty when no Market printed", () => {
    expect(foldLiquidationWindow([])).toEqual({
      totalUsd: 0,
      longUsd: 0,
      shortUsd: 0,
      largestUsd: 0,
      marketCount: 0,
      top: null,
    });
  });

  it("picks the largest total even when the table is sorted by net", () => {
    const rows = rankLiquidationHeat(
      [
        r({ symbol: "ETH", market_index: 1, long_usd: 8000, total_usd: 8000, fill_count: 2 }),
        r({ symbol: "BTC", market_index: 2, short_usd: 2000, total_usd: 2000, fill_count: 1 }),
      ],
      { sort: "net", dir: "desc" }
    );
    expect(rows.map((x) => x.symbol)).toEqual(["BTC", "ETH"]);
    expect(foldLiquidationWindow(rows).top).toEqual({
      symbol: "ETH",
      totalUsd: 8000,
      share: 0.8,
    });
  });
});

describe("Liquidation intensity", () => {
  it("is window liquidations divided by open interest", () => {
    const rows = rankLiquidationHeat(
      [
        r({ symbol: "ETH", market_index: 1, long_usd: 7000, total_usd: 7000, fill_count: 1 }),
        r({ symbol: "BTC", market_index: 2, short_usd: 5000, total_usd: 5000, fill_count: 1 }),
      ],
      { openInterest: { ETH: 100_000, BTC: 10_000 } }
    );
    expect(rows.find((x) => x.symbol === "ETH")?.shareOfOi).toBe(0.07);
    expect(rows.find((x) => x.symbol === "BTC")?.shareOfOi).toBe(0.5);
  });

  it("sorts intensity so a thin book leads when descending", () => {
    const rows = rankLiquidationHeat(
      [
        r({ symbol: "ETH", market_index: 1, long_usd: 7000, total_usd: 7000, fill_count: 1 }),
        r({ symbol: "SOL", market_index: 3, short_usd: 5000, total_usd: 5000, fill_count: 1 }),
      ],
      { sort: "share", dir: "desc", openInterest: { ETH: 100_000, SOL: 10_000 } }
    );
    expect(rows.map((x) => x.symbol)).toEqual(["SOL", "ETH"]);
  });

  it("leaves intensity unknown when open interest is missing, and sorts those last", () => {
    const rows = rankLiquidationHeat(
      [
        r({ symbol: "SOL", market_index: 3, long_usd: 9000, total_usd: 9000, fill_count: 1 }),
        r({ symbol: "ETH", market_index: 1, long_usd: 7000, total_usd: 7000, fill_count: 1 }),
      ],
      { sort: "share", dir: "desc", openInterest: { ETH: 100_000 } }
    );
    expect(rows.map((x) => x.symbol)).toEqual(["ETH", "SOL"]);
    expect(rows.find((x) => x.symbol === "SOL")?.shareOfOi).toBeNull();
  });
});

describe("Largest liquidation and Window share", () => {
  it("keeps the largest print and each Market's fraction of Window total", () => {
    const rows = rankLiquidationHeat([
      r({
        symbol: "ETH",
        market_index: 1,
        long_usd: 8000,
        total_usd: 8000,
        fill_count: 3,
        largest_usd: 5000,
      }),
      r({
        symbol: "BTC",
        market_index: 2,
        short_usd: 2000,
        total_usd: 2000,
        fill_count: 1,
        largest_usd: 2000,
      }),
    ]);
    expect(rows.find((x) => x.symbol === "ETH")?.largestUsd).toBe(5000);
    expect(rows.find((x) => x.symbol === "ETH")?.windowShare).toBe(0.8);
    expect(rows.find((x) => x.symbol === "BTC")?.windowShare).toBe(0.2);
    expect(foldLiquidationWindow(rows).largestUsd).toBe(5000);
  });

  it("sorts so the biggest single liquidation leads when descending", () => {
    const rows = rankLiquidationHeat(
      [
        r({
          symbol: "ETH",
          market_index: 1,
          long_usd: 8000,
          total_usd: 8000,
          fill_count: 4,
          largest_usd: 1000,
        }),
        r({
          symbol: "BTC",
          market_index: 2,
          short_usd: 2000,
          total_usd: 2000,
          fill_count: 1,
          largest_usd: 2000,
        }),
      ],
      { sort: "largest", dir: "desc" }
    );
    expect(rows.map((x) => x.symbol)).toEqual(["BTC", "ETH"]);
  });
});
