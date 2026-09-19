import { afterEach, describe, expect, it } from "vitest";
import type { Account, Asset, Market } from "@/lib/api";
import {
  applyBookDelta,
  applyBookSnapshot,
  applyMarketQuotes,
  clearBook,
  clearMarketQuotes,
  clearMinuteCandles,
  clearTrades,
  getAccount,
  getCandles1s,
  getMarketQuotes,
  getMinuteCandles,
  getTopOfBook,
  isBookSynced,
  overlayQuote,
  prependTrades,
  rollLiveCandles,
  setAccount,
  setMinuteCandles,
  subscribeQuoteDelta,
  upsertMinuteCandle,
  upsertMinuteCandles,
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

describe("getTopOfBook", () => {
  afterEach(() => {
    clearBook();
  });

  it("yields Best Bid and Best Ask price and size from a snapshot", () => {
    applyBookSnapshot({
      bids: [
        { price: "100", size: "1.5" },
        { price: "99", size: "8" },
      ],
      asks: [
        { price: "101", size: "2.25" },
        { price: "102", size: "4" },
      ],
    });
    expect(getTopOfBook()).toEqual({
      bid: { price: "100", size: "1.5" },
      ask: { price: "101", size: "2.25" },
    });
  });

  it("treats a missing or zero-size side as empty", () => {
    applyBookSnapshot({
      bids: [{ price: "100", size: "0" }],
      asks: [{ price: "101", size: "3" }],
    });
    expect(getTopOfBook()).toEqual({
      bid: null,
      ask: { price: "101", size: "3" },
    });
  });

  it("updates when only the Best Bid size changes", () => {
    applyBookSnapshot(
      { bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] },
      10
    );
    applyBookDelta({ bids: [{ price: "100", size: "4" }], asks: [] }, { seq: 11, prevSeq: 10 });
    expect(getTopOfBook()).toEqual({
      bid: { price: "100", size: "4" },
      ask: { price: "101", size: "1" },
    });
  });

  it("does not change when a deeper level updates", () => {
    applyBookSnapshot(
      {
        bids: [
          { price: "100", size: "1" },
          { price: "99", size: "8" },
        ],
        asks: [{ price: "101", size: "1" }],
      },
      10
    );
    applyBookDelta({ bids: [{ price: "99", size: "9" }], asks: [] }, { seq: 11, prevSeq: 10 });
    expect(getTopOfBook()).toEqual({
      bid: { price: "100", size: "1" },
      ask: { price: "101", size: "1" },
    });
  });

  it("is empty after clearBook", () => {
    applyBookSnapshot({ bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] });
    clearBook();
    expect(getTopOfBook()).toEqual({ bid: null, ask: null });
  });

  it("is empty while the book is unsynced", () => {
    applyBookSnapshot(
      { bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] },
      10
    );
    applyBookDelta({ bids: [{ price: "100", size: "2" }], asks: [] }, { seq: 11, prevSeq: 9 });
    expect(isBookSynced()).toBe(false);
    expect(getTopOfBook()).toEqual({ bid: null, ask: null });
  });

  it("returns Top of Book again after a snapshot following a seq gap", () => {
    applyBookSnapshot(
      { bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] },
      10
    );
    applyBookDelta({ bids: [{ price: "100", size: "2" }], asks: [] }, { seq: 11, prevSeq: 9 });
    applyBookSnapshot(
      { bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] },
      20
    );
    expect(getTopOfBook()).toEqual({
      bid: { price: "100", size: "1" },
      ask: { price: "101", size: "1" },
    });
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

describe("minute candles", () => {
  afterEach(() => {
    clearMinuteCandles();
    clearTrades();
  });

  it("buckets unique seconds into one 1m bar", () => {
    upsertMinuteCandle({ time: 1700000040, open: 1, high: 1, low: 1, close: 1, volume: 1 });
    upsertMinuteCandle({ time: 1700000050, open: 2, high: 3, low: 1, close: 2, volume: 1 });
    const bars = getMinuteCandles();
    expect(bars).toHaveLength(1);
    expect(bars[0].time).toBe(1700000040);
    expect(bars[0].close).toBe(2);
  });

  it("keeps history when a closed bar and a new bar arrive together", () => {
    const t0 = 1_700_000_040;
    setMinuteCandles(
      [0, 1, 2].map((i) => ({
        time: t0 + i * 60,
        open: 1,
        high: 1,
        low: 1,
        close: 1,
        volume: 1,
      }))
    );
    upsertMinuteCandles([
      { time: t0 + 120, open: 1, high: 2, low: 1, close: 1.5, volume: 3 },
      { time: t0 + 180, open: 1.5, high: 1.5, low: 1.5, close: 1.5, volume: 0.2 },
    ]);
    const bars = getMinuteCandles();
    expect(bars).toHaveLength(4);
    expect(bars[2].close).toBe(1.5);
    expect(bars[3].time).toBe(t0 + 180);
  });

  it("opens a new 1m bar after the minute elapses without a trade", () => {
    upsertMinuteCandle({ time: 1_700_000_040, open: 1, high: 1, low: 1, close: 2, volume: 1 });
    rollLiveCandles(1_700_000_040 + 70);
    const bars = getMinuteCandles();
    expect(bars).toHaveLength(2);
    expect(bars[1].time).toBe(1_700_000_100);
    expect(bars[1].open).toBe(2);
    expect(bars[1].close).toBe(2);
    expect(bars[1].volume).toBe(0);
  });

  it("opens a new 1s bar after the second elapses without a trade", () => {
    prependTrades([{ price: "10", size: "1", side: "buy", timestamp: 1_700_000_000 }]);
    rollLiveCandles(1_700_000_003);
    const bars = getCandles1s();
    expect(bars.map((b) => b.time)).toEqual([
      1_700_000_000, 1_700_000_001, 1_700_000_002, 1_700_000_003,
    ]);
    expect(bars[3].open).toBe(10);
    expect(bars[3].volume).toBe(0);
  });

  it("caps the live 1m series", () => {
    const bars = Array.from({ length: 2500 }, (_, i) => ({
      time: 1_700_000_000 + i * 60,
      open: 1,
      high: 1,
      low: 1,
      close: 1,
      volume: 1,
    }));
    setMinuteCandles(bars);
    const t0 = Math.floor(1_700_000_000 / 60) * 60;
    expect(getMinuteCandles()).toHaveLength(2000);
    expect(getMinuteCandles()[0].time).toBe(t0 + 500 * 60);
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

  it("fans out only the rows that changed", () => {
    const seen: { market_index: number; mark_price?: number | null }[][] = [];
    const stop = subscribeQuoteDelta((rows) => seen.push(rows));
    applyMarketQuotes([{ market_index: 1, mark_price: 100 }]);
    applyMarketQuotes([{ market_index: 1, mark_price: 100 }]);
    applyMarketQuotes([{ market_index: 2, mark_price: 50 }]);
    stop();
    expect(seen).toEqual([
      [{ market_index: 1, mark_price: 100 }],
      [{ market_index: 2, mark_price: 50 }],
    ]);
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

function accountStub(partial?: Partial<Account>): Account {
  return {
    collateral: "1000",
    available: "1000",
    unrealized_pnl: "0",
    positions: [],
    open_orders: [],
    ...partial,
  };
}

const usdc: Asset = {
  symbol: "USDC",
  balance: "1362.84",
  margin_balance: "16.74",
  available: "16.74",
  index_price: "1",
  ltv: "1",
  usd: "1362.84",
  unrealized_pnl: "",
};

describe("setAccount assets", () => {
  afterEach(() => {
    setAccount(null);
  });

  it("stores assets from a full account payload", () => {
    setAccount(accountStub({ assets: [usdc] }));
    expect(getAccount()?.assets).toEqual([usdc]);
  });

  it("keeps previous assets when a partial message omits the field", () => {
    setAccount(accountStub({ assets: [usdc] }));
    setAccount(accountStub());
    expect(getAccount()?.assets).toEqual([usdc]);
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
