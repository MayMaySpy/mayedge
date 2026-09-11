import { describe, expect, it } from "vitest";
import { orderNotice } from "@/lib/orderNotice";

describe("orderNotice", () => {
  it("titles a market ack as order sent", () => {
    expect(
      orderNotice({ kind: "market", side: "buy", size: "0.01", symbol: "BTC" })
    ).toEqual({
      title: "Order sent",
      description: "Buy 0.01 BTC",
      tone: "bid",
    });
  });

  it("titles an account fill as filled", () => {
    expect(
      orderNotice({
        kind: "fill",
        status: "filled",
        side: "buy",
        size: "0.01",
        symbol: "BTC",
        price: "78500",
      })
    ).toEqual({
      title: "Filled",
      description: "Buy 0.01 BTC · 78500",
      tone: "bid",
    });
  });

  it("includes limit price on a sell", () => {
    expect(
      orderNotice({
        kind: "limit",
        side: "sell",
        size: "1",
        symbol: "ETH",
        price: "2,489.51",
      })
    ).toEqual({
      title: "Order sent",
      description: "Sell 1 ETH · 2,489.51",
      tone: "ask",
    });
  });

  it("names TWAP, chase, and ladder distinctly", () => {
    expect(orderNotice({ kind: "twap", side: "buy", size: "10", symbol: "SOL" }).title).toBe(
      "TWAP sent"
    );
    expect(
      orderNotice({ kind: "twap", status: "active", side: "buy", size: "10", symbol: "SOL" }).title
    ).toBe("TWAP started");
    expect(
      orderNotice({ kind: "chase", side: "sell", size: "0.5", symbol: "BTC", status: "active" })
        .title
    ).toBe("Chase started");
    expect(orderNotice({ kind: "chase", status: "paused", note: "waiting" })).toEqual({
      title: "Chase paused",
      description: "waiting",
      tone: "warn",
    });
    expect(
      orderNotice({ kind: "ladder", side: "buy", size: "2", symbol: "ETH", status: "active" }).title
    ).toBe("Ladder started");
    expect(orderNotice({ kind: "ladder", status: "paused", note: "waiting" })).toEqual({
      title: "Ladder waiting",
      description: "waiting",
      tone: "warn",
    });
    expect(orderNotice({ kind: "ladder", status: "error", note: "rung too small" })).toEqual({
      title: "Ladder failed",
      description: "rung too small",
      tone: "err",
    });
  });

  it("surfaces failures and leverage", () => {
    expect(orderNotice({ kind: "limit", status: "error", note: "min size" })).toEqual({
      title: "Order failed",
      description: "min size",
      tone: "err",
    });
    expect(orderNotice({ kind: "leverage", note: "5x" })).toEqual({
      title: "Leverage set",
      description: "5x",
      tone: "ok",
    });
  });
});
