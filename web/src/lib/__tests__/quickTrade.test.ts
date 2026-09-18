import { describe, expect, it } from "vitest";
import type { Account, Market } from "@/lib/api";
import { buildQuickLimit } from "@/lib/quickTrade";

function market(partial?: Partial<Market>): Market {
  return {
    market_index: 1,
    symbol: "ETH",
    price_decimals: 2,
    size_decimals: 4,
    ...partial,
  } as Market;
}

function account(partial?: Partial<Account>): Account {
  return {
    collateral: "1000",
    available: "1000",
    trade_available: "1000",
    unrealized_pnl: "0",
    positions: [],
    open_orders: [],
    ...partial,
  };
}

describe("buildQuickLimit", () => {
  it("rejects empty or unparsable size", () => {
    const opts = {
      side: "buy" as const,
      price: "99.5",
      market: market(),
      account: account(),
      bbo: { bid: "99", ask: "100" },
    };
    expect(buildQuickLimit({ ...opts, qty: "" })).toEqual({ ok: false, error: "Set a size" });
    expect(buildQuickLimit({ ...opts, qty: "  " })).toEqual({ ok: false, error: "Set a size" });
    expect(buildQuickLimit({ ...opts, qty: "nope" })).toEqual({ ok: false, error: "Set a size" });
  });

  it("rejects a buy larger than the margin max", () => {
    expect(
      buildQuickLimit({
        qty: "10.1",
        side: "buy",
        price: "99.5",
        market: market(),
        account: account(),
        bbo: { bid: "99", ask: "100" },
      })
    ).toEqual({ ok: false, error: "Max 10 ETH" });
  });

  it("returns trimmed size and snapped price", () => {
    expect(
      buildQuickLimit({
        qty: "1.2399",
        side: "sell",
        price: "99.444",
        market: market({ size_decimals: 2 }),
        account: account(),
        bbo: { bid: "99", ask: "100" },
      })
    ).toEqual({ ok: true, size: "1.23", price: "99.44" });
  });
});
