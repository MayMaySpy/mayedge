import { describe, expect, it } from "vitest";
import { isDeskMessage } from "@/lib/deskBridge";

describe("isDeskMessage", () => {
  it("accepts desk-state and quote fan-out", () => {
    expect(
      isDeskMessage({
        type: "desk-state",
        markets: [],
        quotes: [],
        samples: { BTC: [{ t: 1, px: 100 }] },
        symbol: "ETH",
      })
    ).toBe(true);
    expect(isDeskMessage({ type: "quotes", rows: [{ market_index: 1 }] })).toBe(true);
    expect(isDeskMessage({ type: "watch-hello" })).toBe(true);
    expect(isDeskMessage({ type: "watch-closed", samples: {} })).toBe(true);
    expect(isDeskMessage({ type: "desk-closing" })).toBe(true);
    expect(isDeskMessage({ type: "symbol", symbol: "BTC" })).toBe(true);
    expect(isDeskMessage({ type: "markets", markets: [] })).toBe(true);
    expect(isDeskMessage({ type: "desk-ping" })).toBe(true);
    expect(isDeskMessage({ type: "desk-pong" })).toBe(true);
    expect(isDeskMessage({ type: "desk-symbol", symbol: "ZRO" })).toBe(true);
    expect(
      isDeskMessage({
        type: "idea-draft",
        symbol: "ZRO",
        ideaId: "idea-1",
        draft: { entry: 2.19, stop: 2.08, targets: [{ r: "1.91", pct: "100" }] },
      })
    ).toBe(true);
  });

  it("rejects unknown payloads", () => {
    expect(isDeskMessage(null)).toBe(false);
    expect(isDeskMessage({ type: "order_book" })).toBe(false);
    expect(isDeskMessage({ type: "symbol" })).toBe(false);
    expect(isDeskMessage({ type: "desk-symbol", symbol: "" })).toBe(false);
    expect(isDeskMessage({ type: "idea-draft", symbol: "ZRO", ideaId: "idea-1", draft: { entry: 1, stop: 0, targets: [] } })).toBe(false);
    expect(isDeskMessage({ type: "idea-draft", symbol: "ZRO", ideaId: "idea-1", draft: { entry: 1, stop: 2, targets: [{ r: 1, pct: "50" }] } })).toBe(false);
  });
});
