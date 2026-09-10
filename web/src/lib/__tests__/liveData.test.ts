import { afterEach, describe, expect, it } from "vitest";
import type { Market } from "@/lib/api";
import {
  applyBookDelta,
  applyBookSnapshot,
  applyMarketQuotes,
  clearBook,
  clearMarketQuotes,
  clearMinuteCandles,
  clearTrades,
  getCandles1s,
  getMarketQuotes,
  getMinuteCandles,
  isBookSynced,
  overlayQuote,
  prependTrades,
  rollLiveCandles,
  setMinuteCandles,
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
