import { afterEach, describe, expect, it } from "vitest";
import type { Market } from "@/lib/api";
import {
  applyBookDelta,
  applyBookSnapshot,
  applyMarketQuotes,
  clearBook,
  clearMarketQuotes,
  getMarketQuotes,
  isBookSynced,
  overlayQuote,
} from "@/lib/liveData";

describe("applyBookDelta", () => {
  it("returns false and clears sync on seq gap", () => {
    clearBook();
    applyBookSnapshot({ bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] }, 10);
    expect(isBookSynced()).toBe(true);

    const ok = applyBookDelta(
      { bids: [{ price: "100", size: "2" }], asks: [] },
      { seq: 11, prevSeq: 9 }
    );
    expect(ok).toBe(false);
    expect(isBookSynced()).toBe(false);
  });
});

describe("overlayQuote", () => {
  const m = {
    market_index: 1,
    symbol: "ETH",
    price_decimals: 2,
    size_decimals: 4,
    mark_price: 100,
    last_trade_price: 99,
    open_interest: 1e6,
  } as Market;

  it("prefers live mark and last over the snapshot", () => {
    expect(
      overlayQuote(m, { market_index: 1, mark_price: 2000, last_trade_price: 1999 }).mark_price
    ).toBe(2000);
  });

  it("keeps snapshot fields when the quote omits them", () => {
    expect(overlayQuote(m, { market_index: 1, mark_price: 2000 }).open_interest).toBe(1e6);
  });
});

describe("applyMarketQuotes", () => {
  afterEach(() => {
    clearMarketQuotes();
  });

  it("merges mark updates by market index", () => {
    applyMarketQuotes([{ market_index: 1, mark_price: 100, open_interest: 50 }]);
    applyMarketQuotes([{ market_index: 1, mark_price: 101 }]);
    expect(getMarketQuotes()[1]).toMatchObject({ mark_price: 101, open_interest: 50 });
  });
});

describe("applyBookDelta", () => {
  it("returns false and clears sync on seq gap", () => {
    clearBook();
    applyBookSnapshot({ bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] }, 10);
    expect(isBookSynced()).toBe(true);

    const ok = applyBookDelta(
      { bids: [{ price: "100", size: "2" }], asks: [] },
      { seq: 11, prevSeq: 9 }
    );
    expect(ok).toBe(false);
    expect(isBookSynced()).toBe(false);
  });
});
