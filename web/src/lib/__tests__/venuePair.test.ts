import { describe, expect, it } from "vitest";
import { preferPerpMarket, sameMarketIndex, uniqueSymbolMarkets } from "@/lib/algos";
import { liqIdentity, pairLabel } from "@/lib/venuePair";
import type { Market } from "@/lib/api";

describe("pairLabel", () => {
  it("prefixes Lighter as LIT", () => {
    expect(pairLabel("LIT")).toBe("LIT-LIT");
    expect(pairLabel("BTC")).toBe("LIT-BTC");
  });
});

describe("liqIdentity", () => {
  it("keys by trade id", () => {
    expect(liqIdentity("1")).toBe("1");
  });
});

describe("preferPerpMarket", () => {
  it("skips rows without a symbol", () => {
    const markets = [{ market_index: 1 } as Market, { market_index: 2, symbol: "ETH" } as Market];
    expect(preferPerpMarket(markets, "ETH")?.market_index).toBe(2);
    expect(uniqueSymbolMarkets(markets).map((m) => m.symbol)).toEqual(["ETH"]);
  });

  it("prefers the perp when a spot twin exists", () => {
    const markets = [
      { market_index: 9, symbol: "ETH", market_type: "spot", is_perp: false } as Market,
      { market_index: 2, symbol: "ETH", market_type: "perp", is_perp: true } as Market,
    ];
    expect(preferPerpMarket(markets, "ETH")?.market_index).toBe(2);
  });
});

describe("sameMarketIndex", () => {
  it("treats string and number indexes as equal", () => {
    expect(sameMarketIndex("2", 2)).toBe(true);
    expect(sameMarketIndex(2, 9)).toBe(false);
    expect(sameMarketIndex(null, 2)).toBe(false);
  });
});
