import { afterEach, describe, expect, it, vi } from "vitest";
import { canonicalDecimal, decimalInput, parseDecimal } from "@/lib/numbers";
import { chaseQuote, clipQty, roundPassive } from "@/lib/chaseIceberg";
import {
  baseToUsd,
  convertSizeOnUnitToggle,
  formatUsdNotional,
  limitCrossHint,
  makerMinSize,
  maxOrderSize,
  minSizeHint,
  snapReduceOnlySize,
  sizeFieldOtherUnitHint,
  sizePctValue,
  ticketBlockReason,
  ticketSizeFromInput,
  ticketWorkingPrice,
  trimQty,
  usdToBase,
  loadSlipPct,
  persistSlipPct,
} from "@/components/widgets/orderTicket/math";

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

describe("decimalInput", () => {
  it("keeps comma and dot", () => {
    expect(decimalInput("1.234,56")).toBe("1.234,56");
    expect(decimalInput("12,5")).toBe("12,5");
  });

  it("strips letters", () => {
    expect(decimalInput("12,5abc")).toBe("12,5");
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

describe("trimQty", () => {
  it("keeps integer trailing zeros when the size scale is 0", () => {
    expect(trimQty(110, 0)).toBe("110");
    expect(trimQty(100, 0)).toBe("100");
    expect(trimQty(10, 0)).toBe("10");
  });

  it("strips only fractional zeros", () => {
    expect(trimQty(110, 2)).toBe("110");
    expect(trimQty(1.5, 2)).toBe("1.5");
  });
});

describe("makerMinSize", () => {
  it("rounds SKY's $10 minimum up to a whole token", () => {
    expect(makerMinSize(100, 10, 0.094, 0)).toBe(107);
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

describe("ticketWorkingPrice", () => {
  it("uses limit price when set", () => {
    expect(ticketWorkingPrice({ kind: "limit", priceNum: 95, spot: 100 })).toBe(95);
  });

  it("falls back to spot for market", () => {
    expect(ticketWorkingPrice({ kind: "market", priceNum: 0, spot: 100 })).toBe(100);
  });
});

describe("usd notional conversion", () => {
  it("converts usd to floored base", () => {
    expect(usdToBase(10000, 100000, 4)).toBe(0.1);
  });

  it("converts base to usd", () => {
    expect(baseToUsd(0.1, 100000)).toBe(10000);
  });

  it("derives base size from usd input", () => {
    expect(ticketSizeFromInput("10000", "usd", 100000, 4)).toBe(0.1);
  });

  it("keeps base input as base size", () => {
    expect(ticketSizeFromInput("0.1", "base", 100000, 4)).toBe(0.1);
  });

  it("converts on unit toggle", () => {
    expect(convertSizeOnUnitToggle("0.1", "base", "usd", 100000, 4)).toBe("10000");
    expect(convertSizeOnUnitToggle("10000", "usd", "base", 100000, 4)).toBe("0.1");
  });

  it("formats pct chips in usd", () => {
    expect(sizePctValue(100, 0.1, "usd", 100000, 4)).toBe("10000");
  });

  it("shows other-unit hint", () => {
    expect(
      sizeFieldOtherUnitHint({
        raw: "10000",
        unit: "usd",
        symbol: "ETH",
        price: 100000,
        decimals: 4,
        sizeNum: 0.1,
      })
    ).toBe("≈ 0.1 ETH");
    expect(
      sizeFieldOtherUnitHint({
        raw: "0.1",
        unit: "base",
        symbol: "ETH",
        price: 100000,
        decimals: 4,
        sizeNum: 0.1,
      })
    ).toBe(`≈ ${formatUsdNotional(10000)}`);
  });
});

describe("snapReduceOnlySize", () => {
  it("snaps within one size step to full position", () => {
    expect(snapReduceOnlySize(1.9999, 2, 2)).toBe(2);
  });

  it("caps partial close at position", () => {
    expect(snapReduceOnlySize(1.5, 2, 2)).toBe(1.5);
    expect(snapReduceOnlySize(3, 2, 2)).toBe(2);
  });
});

describe("ticketBlockReason", () => {
  const base = {
    tradingEnabled: true,
    feedReady: true,
    sizeNum: 1,
    sizeRaw: "1",
    sizeUnit: "base" as const,
    workingPrice: 100,
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

  it("blocks a usd-sized sell priced far under the bid", () => {
    // $1,000 at a typo'd $10 is 100 ETH, which sells for $10,000 at the $100 bid.
    const typo = {
      ...base,
      kind: "limit" as const,
      sizeUnit: "usd" as const,
      sizeRaw: "1000",
      sizeNum: 100,
      maxSize: 1000,
      workingPrice: 10,
      price: "10",
      sellBid: 100,
    };
    expect(ticketBlockReason(typo)).toBe("Price far below bid — size in ETH");
    // The Buy button never passes a bid: a low buy just rests.
    expect(ticketBlockReason({ ...typo, sellBid: undefined })).toBeNull();
    // Sized in ETH, the price does not change what is sold.
    expect(ticketBlockReason({ ...typo, sizeUnit: "base", sizeRaw: "1", sizeNum: 1 })).toBeNull();
  });

  it("lets a usd-sized sell cross the bid by a little", () => {
    expect(
      ticketBlockReason({
        ...base,
        kind: "limit",
        sizeUnit: "usd",
        sizeRaw: "1000",
        sizeNum: 10.1,
        maxSize: 1000,
        workingPrice: 99,
        price: "99",
        sellBid: 100,
      })
    ).toBeNull();
  });

  it("blocks over max", () => {
    expect(ticketBlockReason({ ...base, sizeNum: 20 })).toMatch(/^Max /);
  });

  it("blocks over max in usd", () => {
    expect(
      ticketBlockReason({
        ...base,
        sizeNum: 20,
        sizeRaw: "2000",
        sizeUnit: "usd",
        workingPrice: 100,
        maxSize: 10,
      })
    ).toBe(`Max ${formatUsdNotional(1000)}`);
  });

  it("blocks usd entry without price", () => {
    expect(
      ticketBlockReason({
        ...base,
        sizeNum: 0,
        sizeRaw: "1000",
        sizeUnit: "usd",
        workingPrice: null,
      })
    ).toBe("No price");
  });

  it("blocks under maker min in usd", () => {
    expect(
      ticketBlockReason({
        ...base,
        kind: "limit",
        price: "100",
        isMaker: true,
        sizeNum: 0.001,
        sizeRaw: "0.1",
        sizeUnit: "usd",
        workingPrice: 100,
        minSz: 0.01,
      })
    ).toBe(`Min ${formatUsdNotional(1)}`);
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

describe("slippage cap", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stores at most 5 percent", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
    });
    persistSlipPct("50");
    expect(loadSlipPct()).toBe("5");
    persistSlipPct("1.5");
    expect(loadSlipPct()).toBe("1.5");
  });
});

describe("limitCrossHint", () => {
  const book = { bid: 100, ask: 100.1, priceDecimals: 2 };

  it("says a Resting Buy at or above the ask fills now", () => {
    expect(limitCrossHint({ ...book, price: 100.1, tif: "gtt" })).toEqual({
      side: "buy",
      text: "A Buy at this price crosses the ask 100.10. It fills now, not resting.",
    });
  });

  it("says a Post only Sell at or below the bid is refused", () => {
    expect(limitCrossHint({ ...book, price: 99.5, tif: "post_only" })).toEqual({
      side: "sell",
      text: "A Sell at this price crosses the bid 100.00. Post only refuses it.",
    });
  });

  it("says nothing inside the spread, for IOC, or without a price or a book", () => {
    expect(limitCrossHint({ ...book, price: 100.05, tif: "gtt" })).toBeNull();
    expect(limitCrossHint({ ...book, price: 101, tif: "ioc" })).toBeNull();
    expect(limitCrossHint({ ...book, price: 0, tif: "gtt" })).toBeNull();
    expect(limitCrossHint({ bid: NaN, ask: NaN, priceDecimals: 2, price: 101, tif: "gtt" })).toBeNull();
  });
});
