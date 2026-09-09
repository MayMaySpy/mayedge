import { describe, expect, it } from "vitest";
import { isSignificantLiq, liqUsd } from "@/lib/liqs";
import type { LiquidationEvent } from "@/lib/api";

function ev(partial: Partial<LiquidationEvent>): LiquidationEvent {
  return {
    trade_id: "1",
    market_index: 0,
    symbol: "ETH",
    kind: "liquidation",
    side: "sell",
    price: "2000",
    size: "2",
    usd_amount: null,
    timestamp: 1,
    ...partial,
  };
}

describe("liqUsd", () => {
  it("prefers usd_amount", () => {
    expect(liqUsd(ev({ usd_amount: "9000", price: "1", size: "1" }))).toBe(9000);
  });

  it("falls back to price * size", () => {
    expect(liqUsd(ev({ usd_amount: null, price: "2000", size: "3" }))).toBe(6000);
  });
});

describe("isSignificantLiq", () => {
  it("marks notionals at or above the floor", () => {
    expect(isSignificantLiq(25_000, 25_000)).toBe(true);
    expect(isSignificantLiq(24_999, 25_000)).toBe(false);
  });

  it("is off when the floor is zero", () => {
    expect(isSignificantLiq(1_000_000, 0)).toBe(false);
  });
});
