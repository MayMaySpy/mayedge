import { describe, expect, it } from "vitest";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import { chaseQuote, clipQty, roundPassive } from "@/lib/chaseIceberg";
import { maxOrderSize, minSizeHint, ticketBlockReason } from "@/components/widgets/orderTicket/math";

describe("parseDecimal", () => {
  it("parses comma decimals", () => {
    expect(parseDecimal("0,5")).toBe(0.5);
  });

  it("parses grouped european decimals", () => {
    expect(parseDecimal("1.234,56")).toBe(1234.56);
  });

  it("returns null for empty", () => {
    expect(parseDecimal("")).toBeNull();
  });
});

describe("canonicalDecimal", () => {
  it("normalizes trailing comma", () => {
    expect(canonicalDecimal("12,5")).toBe("12.5");
  });
});

describe("roundPassive", () => {
  it("floors buys", () => {
    expect(roundPassive(1.015, 0.01, "buy")).toBeCloseTo(1.01, 8);
  });

  it("ceil sells", () => {
    expect(roundPassive(1.015, 0.01, "sell")).toBeCloseTo(1.02, 8);
  });
});

describe("chaseQuote", () => {
  it("rests passive buy below ask", () => {
    const q = chaseQuote({
      side: "buy",
      remaining: 1,
      displayQty: 0.1,
      offsetBps: 0,
      floor: 90,
      ceiling: 110,
      bid: 100,
      ask: 101,
      tick: 0.01,
      minQty: 0.01,
    });
    expect(q.action).toBe("rest");
    expect(q.price).toBe(100);
  });

  it("pauses when book missing", () => {
    const q = chaseQuote({
      side: "buy",
      remaining: 1,
      displayQty: 0.1,
      offsetBps: 0,
      floor: 90,
      ceiling: 110,
      bid: null,
      ask: null,
      tick: 0.01,
      minQty: 0.01,
    });
    expect(q.action).toBe("pause");
    expect(q.reason).toBe("no_book");
  });

  it("aligns clip to qty step like Python golden buy", () => {
    expect(clipQty(10, 1, 0.1)).toBe(1);
    const q = chaseQuote({
      side: "buy",
      remaining: 10,
      displayQty: 1,
      offsetBps: 4,
      floor: 90,
      ceiling: 100,
      bid: 100,
      ask: 100.1,
      tick: 0.01,
      minQty: 0.1,
      qtyStep: 0.1,
    });
    expect(q.action).toBe("rest");
    expect(q.price).toBeCloseTo(99.96, 8);
    expect(q.qty).toBe(1);
  });
});

describe("maxOrderSize", () => {
  it("scales by leverage and price", () => {
    const size = maxOrderSize({
      available: 1000,
      leverage: 10,
      price: 100,
      signedPos: 0,
      side: "buy",
      reduceOnly: false,
    });
    expect(size).toBeCloseTo(100, 4);
  });

  it("caps reduce-only at position size", () => {
    const size = maxOrderSize({
      available: 1000,
      leverage: 10,
      price: 100,
      signedPos: 2,
      side: "sell",
      reduceOnly: true,
    });
    expect(size).toBe(2);
  });
});

describe("minSizeHint", () => {
  it("is silent when min is zero", () => {
    expect(minSizeHint(0, 4, 1)).toBeNull();
  });

  it("shows min before a size is typed", () => {
    expect(minSizeHint(10, 2, 0)).toEqual({ text: "min 10", warn: false });
  });

  it("warns when typed size is below min", () => {
    expect(minSizeHint(10, 2, 5)).toEqual({ text: "Below min 10", warn: true });
  });

  it("stays quiet when size meets min", () => {
    expect(minSizeHint(10, 2, 10)).toEqual({ text: "min 10", warn: false });
  });
});

describe("ticketBlockReason", () => {
  const base = {
    tradingEnabled: true,
    feedReady: true,
    sizeNum: 1,
    maxSize: 10,
    symbol: "ETH",
    decimals: 2,
    kind: "market" as const,
    price: "",
    isMaker: false,
    minSz: 0.01,
    algoBlocked: null as string | null,
  };

  it("blocks when trading off", () => {
    expect(ticketBlockReason({ ...base, tradingEnabled: false })).toBe("Trading not configured");
  });

  it("blocks when feed down", () => {
    expect(ticketBlockReason({ ...base, feedReady: false, feedReason: "Reconnecting" })).toBe(
      "Reconnecting"
    );
  });

  it("blocks empty size", () => {
    expect(ticketBlockReason({ ...base, sizeNum: 0 })).toBe("Enter size");
  });

  it("blocks over max", () => {
    expect(ticketBlockReason({ ...base, sizeNum: 20 })).toMatch(/^Max /);
  });

  it("skips max when omitted", () => {
    expect(ticketBlockReason({ ...base, maxSize: undefined, sizeNum: 99 })).toBeNull();
  });

  it("blocks limit without price", () => {
    expect(ticketBlockReason({ ...base, kind: "limit", price: "" })).toBe("Enter price");
  });

  it("blocks under maker min", () => {
    expect(ticketBlockReason({ ...base, kind: "limit", price: "100", isMaker: true, sizeNum: 0.001 })).toMatch(
      /^Min /
    );
  });

  it("forwards algo plugin block reason", () => {
    expect(
      ticketBlockReason({ ...base, kind: "algo", algoBlocked: "Set floor / ceiling" })
    ).toBe("Set floor / ceiling");
  });

  it("allows valid market order", () => {
    expect(ticketBlockReason(base)).toBeNull();
  });
});
