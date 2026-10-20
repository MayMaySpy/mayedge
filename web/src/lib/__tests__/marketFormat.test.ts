import { beforeEach, describe, expect, it } from "vitest";
import type { Market } from "@/lib/api";
import { marketPrice, marketSize, setMarketDecimals } from "@/lib/marketFormat";
import { formatPrice } from "@/lib/utils";

const market = (symbol: string, price_decimals: number, size_decimals: number, is_perp = true) =>
  ({ symbol, price_decimals, size_decimals, is_perp, market_index: 0 }) as Market;


beforeEach(() => {
  setMarketDecimals([market("PUMP", 6, 0), market("BTC", 1, 5), market("WLD", 5, 1), market("ETH", 2, 4)]);
});

describe("market precision", () => {
  it("shows a price at exactly its market's tick", () => {
    expect(marketPrice("0.004813", "PUMP")).toBe((0.004813).toLocaleString(undefined, { minimumFractionDigits: 6 }));
    expect(marketPrice("0.0048", "PUMP")).toBe((0.0048).toLocaleString(undefined, { minimumFractionDigits: 6 }));
    expect(marketPrice("82759.4", "BTC")).toBe((82759.4).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
    expect(marketPrice("0.58773", "WLD")).toBe((0.58773).toLocaleString(undefined, { minimumFractionDigits: 5 }));
  });

  it("never hides a small price's digits when the market is unknown", () => {
    expect(marketPrice("0.004813", "NOPE")).toBe((0.004813).toLocaleString(undefined, { maximumFractionDigits: 8 }));
    expect(formatPrice("0.00012")).not.toBe(formatPrice("0.0001"));
  });

  it("cuts a size to its market's lot", () => {
    expect(marketSize("100000", "PUMP")).toBe((100000).toLocaleString());
    expect(marketSize("0.123456789", "BTC")).toBe((0.12346).toLocaleString(undefined, { maximumFractionDigits: 5 }));
  });

  it("prefers the perp when a spot market shares the symbol", () => {
    setMarketDecimals([market("ETH", 2, 4), market("ETH", 4, 4, false)]);
    expect(marketPrice("2447.95", "ETH")).toBe((2447.95).toLocaleString(undefined, { minimumFractionDigits: 2 }));
  });
});
