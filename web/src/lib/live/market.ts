/** Live market data: the book, Top of Book, trades, candles and every Market's quote. */
import { useCallback, useSyncExternalStore } from "react";
import type { Candle, Market } from "@/lib/api";
import { makeThrottledNotify } from "@/lib/live/notify";

export interface OrderBookLevel {
  price: string;
  size: string;
}

export interface Trade {
  price: string;
  size: string;
  side: string;
  timestamp: number;
  tx_hash?: string;
  bid_account_id?: number;
  ask_account_id?: number;
}

type Book = { bids: OrderBookLevel[]; asks: OrderBookLevel[] };
/** Best bid/ask prices only — for consumers that don't need depth. */
export type Bbo = { bid: string | null; ask: string | null };
/** Best Bid and Best Ask together, each with resting size. */
export type TopOfBook = {
  bid: OrderBookLevel | null;
  ask: OrderBookLevel | null;
};
const EMPTY_TOP: TopOfBook = { bid: null, ask: null };

const MAX_TRADES = 200;
const MAX_1S = 3600;
/** 1m live series — uncapped upserts were growing the chart until the tab OOMed. */
const MAX_MINUTE = 2000;
const BOOK_DEPTH = 250;

let book: Book = { bids: [], asks: [] };
let bookSeq = 0;
let bookSynced = false;
const bookListeners = new Set<() => void>();

let bbo: Bbo = { bid: null, ask: null };
const bboListeners = new Set<() => void>();

let top: TopOfBook = EMPTY_TOP;
const topListeners = new Set<() => void>();

/** Coalesce React notifies — never flush inside the WS handler (that freezes paint). */
const BOOK_UI_MS = 150;
let bookFlushTimer: ReturnType<typeof setTimeout> | null = null;
let bookNotifyPending = false;
let bboNotifyPending = false;
let topNotifyPending = false;
let lastBookFlushAt = 0;

let trades: Trade[] = [];

let candles1s: Candle[] = [];

/** 1m candles from market WS — kept out of Dashboard React state. */
let candlesMin: Candle[] = [];

function topPrice(levels: OrderBookLevel[]): string | null {
  const p = levels[0]?.price;
  return p != null && p !== "" ? p : null;
}

function bboFromBook(next: Book): Bbo {
  return { bid: topPrice(next.bids), ask: topPrice(next.asks) };
}

function topLevel(levels: OrderBookLevel[]): OrderBookLevel | null {
  const l = levels[0];
  if (!l?.price) return null;
  if (!(parseFloat(l.size) || 0)) return null;
  return l;
}

function topFromBook(next: Book): TopOfBook {
  const bid = topLevel(next.bids);
  const ask = topLevel(next.asks);
  if (!bid && !ask) return EMPTY_TOP;
  return { bid, ask };
}

function sameLevel(a: OrderBookLevel | null, b: OrderBookLevel | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.price === b.price && a.size === b.size;
}

function sameTop(a: TopOfBook, b: TopOfBook): boolean {
  return sameLevel(a.bid, b.bid) && sameLevel(a.ask, b.ask);
}

function flushBookNotifies() {
  bookFlushTimer = null;
  lastBookFlushAt = performance.now();
  const notifyBook = bookNotifyPending;
  const notifyBbo = bboNotifyPending;
  const notifyTop = topNotifyPending;
  bookNotifyPending = false;
  bboNotifyPending = false;
  topNotifyPending = false;
  if (notifyBook) bookListeners.forEach((fn) => fn());
  if (notifyBbo) bboListeners.forEach((fn) => fn());
  if (notifyTop) topListeners.forEach((fn) => fn());
}

function scheduleBookNotify(opts: { book: boolean; bbo: boolean; top: boolean }) {
  if (opts.book) bookNotifyPending = true;
  if (opts.bbo) bboNotifyPending = true;
  if (opts.top) topNotifyPending = true;
  if (bookFlushTimer != null) return;
  const wait = Math.max(0, BOOK_UI_MS - (performance.now() - lastBookFlushAt));
  bookFlushTimer = setTimeout(flushBookNotifies, wait);
}

function sidesEqual(a: OrderBookLevel[], b: OrderBookLevel[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].price !== b[i].price || a[i].size !== b[i].size) return false;
  }
  return true;
}

function publishBook(next: Book) {
  const sameBids = sidesEqual(book.bids, next.bids);
  const sameAsks = sidesEqual(book.asks, next.asks);
  const merged: Book = {
    bids: sameBids ? book.bids : next.bids,
    asks: sameAsks ? book.asks : next.asks,
  };
  const nextBbo = bboFromBook(merged);
  const bboChanged = nextBbo.bid !== bbo.bid || nextBbo.ask !== bbo.ask;
  const nextTop = topFromBook(merged);
  const topChanged = !sameTop(top, nextTop);
  const bookChanged = !sameBids || !sameAsks;
  if (!bookChanged && !bboChanged && !topChanged) return;
  book = merged;
  if (bboChanged) bbo = nextBbo;
  if (topChanged) top = nextTop;
  scheduleBookNotify({ book: bookChanged, bbo: bboChanged, top: topChanged });
}

/** Backend already sorts; just drop empties and cap depth. */
function takeSide(levels: OrderBookLevel[]): OrderBookLevel[] {
  const out: OrderBookLevel[] = [];
  for (let i = 0; i < levels.length && out.length < BOOK_DEPTH; i++) {
    const l = levels[i];
    if (l.price && (parseFloat(l.size) || 0) > 0) out.push(l);
  }
  return out;
}

function levelPrice(level: OrderBookLevel): number {
  return parseFloat(level.price) || 0;
}

function sortSide(levels: OrderBookLevel[], bids: boolean): OrderBookLevel[] {
  const kept = levels.filter((l) => (parseFloat(l.size) || 0) > 0 && l.price);
  kept.sort((a, b) => (bids ? levelPrice(b) - levelPrice(a) : levelPrice(a) - levelPrice(b)));
  return kept.slice(0, BOOK_DEPTH);
}

function mergeSide(
  existing: OrderBookLevel[],
  updates: OrderBookLevel[],
  bids: boolean
): OrderBookLevel[] {
  const byPrice = new Map(existing.map((l) => [l.price, l]));
  for (const lvl of updates) {
    const size = parseFloat(lvl.size) || 0;
    if (size <= 0) byPrice.delete(lvl.price);
    else byPrice.set(lvl.price, lvl);
  }
  return sortSide([...byPrice.values()], bids);
}

function tradeUnix(timestamp: number) {
  if (!timestamp) return 0;
  return timestamp > 1e12 ? Math.floor(timestamp / 1000) : timestamp;
}

function applyTradeTo1s(t: Trade) {
  const ts = tradeUnix(t.timestamp);
  const px = parseFloat(t.price);
  const sz = parseFloat(t.size) || 0;
  if (!ts || !px) return;
  const last = candles1s[candles1s.length - 1];
  if (last && last.time === ts) {
    // Mutate last bar then replace array ref — avoid copying 3600 bars per trade.
    last.high = Math.max(last.high, px);
    last.low = Math.min(last.low, px);
    last.close = px;
    last.volume += sz;
    candles1s = candles1s.slice();
    return;
  }
  if (!last || ts > last.time) {
    candles1s = [...candles1s, { time: ts, open: px, high: px, low: px, close: px, volume: sz }];
    if (candles1s.length > MAX_1S) candles1s = candles1s.slice(-MAX_1S);
  }
}

/** Trailing throttle — never notify React from the WS callback. */
const tradesNotify = makeThrottledNotify(100);
const candle1sNotify = makeThrottledNotify(100);
const minuteCandleNotify = makeThrottledNotify(100);
const quoteNotify = makeThrottledNotify(100);

export type MarketQuote = {
  market_index: number;
  mark_price?: number | null;
  last_trade_price?: number | null;
  index_price?: number | null;
  change_24h?: number | null;
  open_interest?: number | null;
  funding_rate?: number | null;
  funding_apr?: number | null;
  volume_24h?: number | null;
  best_bid_price?: number | null;
  best_ask_price?: number | null;
  mid_price?: number | null;
};

const emptyQuotes: Record<number, MarketQuote> = {};
let quotes: Record<number, MarketQuote> = emptyQuotes;
const quoteDeltaListeners = new Set<(rows: MarketQuote[]) => void>();

/** The socket's markets are a snapshot from when it connected, so a polled row wins. */
export function mergeMarkets(snapshot: readonly Market[], polled: readonly Market[]): Market[] {
  const byIndex = new Map<number, Market>();
  for (const m of snapshot) {
    if (m?.market_index == null) continue;
    byIndex.set(m.market_index, m);
  }
  for (const m of polled) {
    if (m?.market_index == null) continue;
    const prev = byIndex.get(m.market_index);
    byIndex.set(m.market_index, prev ? { ...prev, ...m } : m);
  }
  return [...byIndex.values()];
}

export function overlayQuote(m: Market, q?: MarketQuote | null): Market {
  if (!q) return m;
  return {
    ...m,
    mark_price: q.mark_price ?? m.mark_price,
    last_trade_price: q.last_trade_price ?? m.last_trade_price,
    index_price: q.index_price ?? m.index_price,
    change_24h: q.change_24h ?? m.change_24h,
    open_interest: q.open_interest ?? m.open_interest,
    funding_rate: q.funding_rate ?? m.funding_rate,
    funding_apr: q.funding_apr ?? m.funding_apr,
    volume_24h: q.volume_24h ?? m.volume_24h,
    best_bid_price: q.best_bid_price ?? m.best_bid_price,
    best_ask_price: q.best_ask_price ?? m.best_ask_price,
    mid_price: q.mid_price ?? m.mid_price,
  };
}

export function applyMarketQuotes(rows: MarketQuote[]) {
  if (!rows.length) return;
  let changed = false;
  const changedRows: MarketQuote[] = [];
  const next = { ...quotes };
  for (const row of rows) {
    if (row.market_index == null) continue;
    const prev = next[row.market_index];
    const merged = prev ? { ...prev, ...row } : row;
    if (
      prev &&
      prev.mark_price === merged.mark_price &&
      prev.last_trade_price === merged.last_trade_price &&
      prev.open_interest === merged.open_interest &&
      prev.funding_rate === merged.funding_rate &&
      prev.change_24h === merged.change_24h &&
      prev.index_price === merged.index_price
    ) {
      continue;
    }
    next[row.market_index] = merged;
    changedRows.push(merged);
    changed = true;
  }
  if (!changed) return;
  quotes = next;
  quoteNotify.notify();
  quoteDeltaListeners.forEach((fn) => fn(changedRows));
}

export function getMarketQuotes() {
  return quotes;
}

export function clearMarketQuotes() {
  quotes = emptyQuotes;
  quoteNotify.notifyNow();
}

export function subscribeMarketQuotes(onChange: () => void) {
  return quoteNotify.subscribe(onChange);
}

export function subscribeQuoteDelta(onRows: (rows: MarketQuote[]) => void) {
  quoteDeltaListeners.add(onRows);
  return () => {
    quoteDeltaListeners.delete(onRows);
  };
}

export function useLiveQuotes() {
  return useSyncExternalStore(subscribeMarketQuotes, getMarketQuotes, getMarketQuotes);
}

/** One market's open interest. Other markets' quotes do not render the subscriber. */
export function liveOpenInterest(marketIndex: number | null | undefined): number | null {
  if (marketIndex == null) return null;
  const oi = quotes[marketIndex]?.open_interest;
  return oi != null && Number.isFinite(oi) ? oi : null;
}

export function useLiveOpenInterest(marketIndex: number | null | undefined): number | null {
  const subscribe = useCallback(
    (onChange: () => void) =>
      subscribeQuoteDelta((rows) => {
        if (marketIndex == null) return;
        if (rows.some((row) => row.market_index === marketIndex)) onChange();
      }),
    [marketIndex]
  );
  const get = useCallback(() => liveOpenInterest(marketIndex), [marketIndex]);
  return useSyncExternalStore(subscribe, get, get);
}

/** One market's 1h funding estimate, in percent. */
export function liveFundingRate(marketIndex: number | null | undefined): number | null {
  if (marketIndex == null) return null;
  const rate = quotes[marketIndex]?.funding_rate;
  return rate != null && Number.isFinite(rate) ? rate : null;
}

export function useLiveFundingRate(marketIndex: number | null | undefined): number | null {
  const subscribe = useCallback(
    (onChange: () => void) =>
      subscribeQuoteDelta((rows) => {
        if (marketIndex == null) return;
        if (rows.some((row) => row.market_index === marketIndex)) onChange();
      }),
    [marketIndex]
  );
  const get = useCallback(() => liveFundingRate(marketIndex), [marketIndex]);
  return useSyncExternalStore(subscribe, get, get);
}

export function subscribeBook(onChange: () => void) {
  bookListeners.add(onChange);
  return () => {
    bookListeners.delete(onChange);
  };
}

export function getBook() {
  return book;
}

export function subscribeBbo(onChange: () => void) {
  bboListeners.add(onChange);
  return () => {
    bboListeners.delete(onChange);
  };
}

export function getBbo() {
  return bbo;
}

export function subscribeTopOfBook(onChange: () => void) {
  topListeners.add(onChange);
  return () => {
    topListeners.delete(onChange);
  };
}

export function getTopOfBook(): TopOfBook {
  if (!bookSynced) return EMPTY_TOP;
  return top;
}

/** Full replace from gateway snapshot (or legacy `order_book`). */
export function applyBookSnapshot(
  next: Book,
  seq?: number | null
) {
  bookSynced = true;
  if (typeof seq === "number" && Number.isFinite(seq)) bookSeq = seq;
  publishBook({
    bids: takeSide(next.bids ?? []),
    asks: takeSide(next.asks ?? []),
  });
}

/** Incremental Lighter-style delta. Returns false if seq gap (wait for snapshot). */
export function applyBookDelta(
  delta: Book,
  opts?: { seq?: number | null; prevSeq?: number | null }
): boolean {
  const prevSeq = opts?.prevSeq;
  const seq = opts?.seq;
  if (!bookSynced) return false;
  if (typeof prevSeq === "number" && Number.isFinite(prevSeq) && prevSeq !== bookSeq) {
    bookSynced = false;
    if (top !== EMPTY_TOP) top = EMPTY_TOP;
    topListeners.forEach((fn) => fn());
    return false;
  }
  if (typeof seq === "number" && Number.isFinite(seq)) bookSeq = seq;
  const db = delta.bids ?? [];
  const da = delta.asks ?? [];
  if (!db.length && !da.length) return true;
  publishBook({
    bids: mergeSide(book.bids, db, true),
    asks: mergeSide(book.asks, da, false),
  });
  return true;
}

/** @deprecated Prefer applyBookSnapshot — kept for any leftover callers. */
export function setBook(next: Book) {
  applyBookSnapshot(next);
}

export function clearBook() {
  bookSeq = 0;
  bookSynced = false;
  const topChanged = top !== EMPTY_TOP;
  if (
    book.bids.length === 0 &&
    book.asks.length === 0 &&
    bbo.bid == null &&
    bbo.ask == null &&
    !topChanged
  ) {
    return;
  }
  book = { bids: [], asks: [] };
  const bboChanged = bbo.bid != null || bbo.ask != null;
  if (bboChanged) bbo = { bid: null, ask: null };
  if (topChanged) top = EMPTY_TOP;
  if (bookFlushTimer != null) {
    clearTimeout(bookFlushTimer);
    bookFlushTimer = null;
  }
  bookNotifyPending = false;
  bboNotifyPending = false;
  topNotifyPending = false;
  lastBookFlushAt = 0;
  bookListeners.forEach((fn) => fn());
  if (bboChanged) bboListeners.forEach((fn) => fn());
  if (topChanged) topListeners.forEach((fn) => fn());
}

export function getBookSeq() {
  return bookSeq;
}

export function isBookSynced() {
  return bookSynced;
}

export function setBookSynced(synced: boolean) {
  if (bookSynced === synced) return;
  bookSynced = synced;
  bookListeners.forEach((fn) => fn());
  topListeners.forEach((fn) => fn());
}

export function subscribeTrades(onChange: () => void) {
  return tradesNotify.subscribe(onChange);
}

export function getTrades() {
  return trades;
}

export function prependTrades(incoming: Trade[]) {
  if (!incoming.length) return;
  trades = incoming.concat(trades).slice(0, MAX_TRADES);
  for (let i = incoming.length - 1; i >= 0; i--) applyTradeTo1s(incoming[i]);
  tradesNotify.notify();
  candle1sNotify.notify();
}

export function clearTrades() {
  const hadTrades = trades.length > 0;
  const had1s = candles1s.length > 0;
  trades = [];
  candles1s = [];
  if (hadTrades) tradesNotify.notifyNow();
  if (had1s) candle1sNotify.notifyNow();
}

export function subscribeCandles1s(onChange: () => void) {
  return candle1sNotify.subscribe(onChange);
}

export function getCandles1s() {
  return candles1s;
}

function unixSec(t: number): number {
  if (!Number.isFinite(t) || t <= 0) return 0;
  return t > 1e12 ? Math.floor(t / 1000) : Math.floor(t);
}

export function seedCandles1s(next: Candle[]) {
  if (!next.length) return;
  const norm = next
    .map((c) => ({ ...c, time: unixSec(c.time) }))
    .filter((c) => c.time > 0);
  if (!norm.length) return;
  if (!candles1s.length) {
    candles1s = norm.slice(-MAX_1S);
  } else {
    const firstLive = unixSec(candles1s[0].time);
    const older = norm.filter((c) => c.time < firstLive);
    candles1s = [...older, ...candles1s].slice(-MAX_1S);
  }
  candle1sNotify.notifyNow();
}

export function subscribeMinuteCandles(onChange: () => void) {
  return minuteCandleNotify.subscribe(onChange);
}

export function getMinuteCandles() {
  return candlesMin;
}

function capMinute(next: Candle[]): Candle[] {
  return next.length > MAX_MINUTE ? next.slice(-MAX_MINUTE) : next;
}

function minuteBar(c: Candle): Candle | null {
  const t = unixSec(c.time);
  if (!t) return null;
  return { ...c, time: Math.floor(t / 60) * 60 };
}

export function setMinuteCandles(next: Candle[]) {
  const byT = new Map<number, Candle>();
  for (const raw of next) {
    const bar = minuteBar(raw);
    if (bar) byT.set(bar.time, bar);
  }
  candlesMin = capMinute([...byT.values()].sort((a, b) => a.time - b.time));
  minuteCandleNotify.notifyNow();
}

export function upsertMinuteCandles(rows: Candle[]) {
  if (!rows.length) return;
  for (const row of rows) upsertMinuteCandle(row);
}

export function upsertMinuteCandle(c: Candle) {
  const bar = minuteBar(c);
  if (!bar) return;
  const candles = candlesMin;
  const last = candles[candles.length - 1];
  if (last && last.time === bar.time) {
    const next = candles.slice();
    next[next.length - 1] = bar;
    candlesMin = next;
    minuteCandleNotify.notify();
    return;
  }
  const idx = candles.findIndex((x) => x.time === bar.time);
  if (idx >= 0) {
    const next = candles.slice();
    next[idx] = bar;
    candlesMin = next;
    minuteCandleNotify.notify();
    return;
  }
  if (last && bar.time < last.time) {
    candlesMin = capMinute(
      [...candles, bar].sort((a, b) => a.time - b.time)
    );
    minuteCandleNotify.notify();
    return;
  }
  candlesMin = capMinute([...candles, bar]);
  minuteCandleNotify.notify();
}

export function clearMinuteCandles() {
  if (!candlesMin.length) return;
  candlesMin = [];
  minuteCandleNotify.notifyNow();
}

function emptyBar(time: number, px: number): Candle {
  return { time, open: px, high: px, low: px, close: px, volume: 0 };
}

const MAX_1S_FILL = 5;
const MAX_MIN_FILL = 2;

/** Close the forming bar when the period elapses, even if no trade arrived. */
export function rollLiveCandles(nowSec = Math.floor(Date.now() / 1000)) {
  if (!Number.isFinite(nowSec) || nowSec <= 0) return;
  const now = Math.floor(nowSec);

  if (candles1s.length) {
    const last = candles1s[candles1s.length - 1];
    if (now > last.time) {
      const gap = now - last.time;
      const start = gap > MAX_1S_FILL ? now : last.time + 1;
      const add: Candle[] = [];
      for (let t = start; t <= now; t++) add.push(emptyBar(t, last.close));
      candles1s = [...candles1s, ...add];
      if (candles1s.length > MAX_1S) candles1s = candles1s.slice(-MAX_1S);
      candle1sNotify.notify();
    }
  }

  if (candlesMin.length) {
    const bucket = Math.floor(now / 60) * 60;
    const last = candlesMin[candlesMin.length - 1];
    if (bucket > last.time) {
      const gapMin = (bucket - last.time) / 60;
      const start = gapMin > MAX_MIN_FILL ? bucket : last.time + 60;
      const add: Candle[] = [];
      for (let t = start; t <= bucket; t += 60) add.push(emptyBar(t, last.close));
      candlesMin = capMinute([...candlesMin, ...add]);
      minuteCandleNotify.notify();
    }
  }
}

export function useLiveBook() {
  return useSyncExternalStore(subscribeBook, getBook, getBook);
}

/** Best bid/ask only — avoids re-rendering on depth-only book updates. */
export function useLiveBbo() {
  return useSyncExternalStore(subscribeBbo, getBbo, getBbo);
}

/** Top of Book — notifies when Best Bid/Ask price or size changes, not deeper levels. */
export function useLiveTopOfBook() {
  return useSyncExternalStore(subscribeTopOfBook, getTopOfBook, getTopOfBook);
}

export function useLiveTrades() {
  return useSyncExternalStore(subscribeTrades, getTrades, getTrades);
}

const EMPTY_CANDLES: Candle[] = [];
function subscribeNoop(_onChange: () => void) {
  return () => {};
}
function getEmptyCandles() {
  return EMPTY_CANDLES;
}

export function useLiveCandles1s(enabled = true) {
  return useSyncExternalStore(
    enabled ? subscribeCandles1s : subscribeNoop,
    enabled ? getCandles1s : getEmptyCandles,
    enabled ? getCandles1s : getEmptyCandles
  );
}

export function useLiveMinuteCandles() {
  return useSyncExternalStore(subscribeMinuteCandles, getMinuteCandles, getMinuteCandles);
}

/** Deliver every held market notice now, e.g. when the tab comes back. */
export function flushMarketUi() {
  rollLiveCandles();
  tradesNotify.notifyNow();
  candle1sNotify.notifyNow();
  minuteCandleNotify.notifyNow();
  quoteNotify.notifyNow();
}
