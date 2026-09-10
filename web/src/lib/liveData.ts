import { useSyncExternalStore } from "react";
import type { Account, AccountTrade, AlgoBook, AlgoState, Candle, AlertEvent, Market } from "@/lib/api";
import { algoIsWorking } from "@/lib/algos";
import { liqIdentity } from "@/lib/venuePair";

export interface OrderBookLevel {
  price: string;
  size: string;
}

export interface Trade {
  price: string;
  size: string;
  side: string;
  timestamp: number;
}

type Book = { bids: OrderBookLevel[]; asks: OrderBookLevel[] };
/** Best bid/ask prices only — for consumers that don't need depth. */
export type Bbo = { bid: string | null; ask: string | null };

const MAX_TRADES = 200;
const MAX_1S = 3600;
/** 1m live series — uncapped upserts were growing the chart until the tab OOMed. */
const MAX_MINUTE = 2000;
const BOOK_DEPTH = 40;

let book: Book = { bids: [], asks: [] };
let bookSeq = 0;
let bookSynced = false;
const bookListeners = new Set<() => void>();

let bbo: Bbo = { bid: null, ask: null };
const bboListeners = new Set<() => void>();

/** Coalesce React notifies — never flush inside the WS handler (that freezes paint). */
const BOOK_UI_MS = 150;
let bookFlushTimer: ReturnType<typeof setTimeout> | null = null;
let bookNotifyPending = false;
let bboNotifyPending = false;
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

function flushBookNotifies() {
  bookFlushTimer = null;
  lastBookFlushAt = performance.now();
  const notifyBook = bookNotifyPending;
  const notifyBbo = bboNotifyPending;
  bookNotifyPending = false;
  bboNotifyPending = false;
  if (notifyBook) bookListeners.forEach((fn) => fn());
  if (notifyBbo) bboListeners.forEach((fn) => fn());
}

function scheduleBookNotify(opts: { book: boolean; bbo: boolean }) {
  if (opts.book) bookNotifyPending = true;
  if (opts.bbo) bboNotifyPending = true;
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
  if (sameBids && sameAsks) return;
  const merged: Book = {
    bids: sameBids ? book.bids : next.bids,
    asks: sameAsks ? book.asks : next.asks,
  };
  const nextBbo = bboFromBook(merged);
  const bboChanged = nextBbo.bid !== bbo.bid || nextBbo.ask !== bbo.ask;
  book = merged;
  if (bboChanged) bbo = nextBbo;
  scheduleBookNotify({ book: true, bbo: bboChanged });
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
function makeThrottledNotify(ms: number) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending = false;
  let lastAt = 0;
  const listeners = new Set<() => void>();

  const flush = () => {
    timer = null;
    lastAt = performance.now();
    if (!pending) return;
    pending = false;
    listeners.forEach((fn) => fn());
  };

  return {
    listeners,
    subscribe(onChange: () => void) {
      listeners.add(onChange);
      return () => {
        listeners.delete(onChange);
      };
    },
    notify() {
      pending = true;
      if (timer != null) return;
      const wait = Math.max(0, ms - (performance.now() - lastAt));
      timer = setTimeout(flush, wait);
    },
    notifyNow() {
      if (timer != null) {
        clearTimeout(timer);
        timer = null;
      }
      pending = false;
      lastAt = 0;
      listeners.forEach((fn) => fn());
    },
  };
}

const tradesNotify = makeThrottledNotify(100);
const candle1sNotify = makeThrottledNotify(100);
const minuteCandleNotify = makeThrottledNotify(100);
const accountNotify = makeThrottledNotify(150);
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
    changed = true;
  }
  if (!changed) return;
  quotes = next;
  quoteNotify.notify();
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

export function useLiveQuotes() {
  return useSyncExternalStore(subscribeMarketQuotes, getMarketQuotes, getMarketQuotes);
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
  if (book.bids.length === 0 && book.asks.length === 0 && bbo.bid == null && bbo.ask == null) {
    return;
  }
  book = { bids: [], asks: [] };
  const bboChanged = bbo.bid != null || bbo.ask != null;
  if (bboChanged) bbo = { bid: null, ask: null };
  if (bookFlushTimer != null) {
    clearTimeout(bookFlushTimer);
    bookFlushTimer = null;
  }
  bookNotifyPending = false;
  bboNotifyPending = false;
  lastBookFlushAt = 0;
  bookListeners.forEach((fn) => fn());
  if (bboChanged) bboListeners.forEach((fn) => fn());
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

let account: Account | null = null;

/** Prefer a positive live balance over flaky WS/REST zeros. */
function preferBalance(prev: string | undefined, next: string | undefined): string {
  const nf = parseFloat(next ?? "");
  const pf = parseFloat(prev ?? "");
  if (Number.isFinite(nf) && nf > 0) return String(next);
  if (Number.isFinite(pf) && pf > 0 && (!Number.isFinite(nf) || nf <= 0)) return prev!;
  if (next != null && next !== "" && Number.isFinite(nf)) return String(next);
  return prev ?? "0";
}

/** Keep multi-asset trade capacity; don't fall back to plain available. */
function preferTradeAvailable(
  prev: string | undefined,
  next: string | undefined,
  available: string | undefined
): string {
  const n = parseFloat(next ?? "");
  const p = parseFloat(prev ?? "");
  const a = parseFloat(available ?? "");
  if (Number.isFinite(n) && n > 0) {
    // Ignore USDC-only collapses while we still have multi-asset headroom.
    if (
      Number.isFinite(p) &&
      Number.isFinite(a) &&
      a > 0 &&
      p > a * 1.05 &&
      Math.abs(n - a) <= Math.max(1, a * 0.02)
    ) {
      return prev!;
    }
    return String(next);
  }
  if (Number.isFinite(p) && p > 0) return prev!;
  if (Number.isFinite(a) && a > 0) return String(available);
  return prev ?? next ?? "0";
}

export function subscribeAccount(onChange: () => void) {
  return accountNotify.subscribe(onChange);
}

export function getAccount() {
  return account;
}

export function setAccount(next: Account | null) {
  if (!next) {
    account = null;
    accountNotify.notifyNow();
    return;
  }
  const prev = account;
  const hasOrders = Object.prototype.hasOwnProperty.call(next, "open_orders");
  const hasPositions = Object.prototype.hasOwnProperty.call(next, "positions");
  account = {
    collateral: preferBalance(prev?.collateral, next.collateral),
    available: preferBalance(prev?.available, next.available),
    trade_available: preferTradeAvailable(
      prev?.trade_available,
      next.trade_available,
      next.available ?? prev?.available
    ),
    unrealized_pnl: next.unrealized_pnl ?? prev?.unrealized_pnl ?? "0",
    positions: hasPositions ? (next.positions ?? []) : (prev?.positions ?? []),
    open_orders: hasOrders ? (next.open_orders ?? []) : (prev?.open_orders ?? []),
  };
  accountNotify.notify();
}

export function useLiveAccount() {
  return useSyncExternalStore(subscribeAccount, getAccount, getAccount);
}

const MAX_ACCOUNT_TRADES = 200;
let accountTrades: AccountTrade[] = [];
const accountTradesNotify = makeThrottledNotify(100);

export function subscribeAccountTrades(onChange: () => void) {
  return accountTradesNotify.subscribe(onChange);
}

export function getAccountTrades() {
  return accountTrades;
}

/** Prepend live account fills from WS; dedupe by trade_id. */
export function prependAccountTrades(incoming: AccountTrade[]) {
  if (!incoming.length) return;
  const byId = new Map<string, AccountTrade>();
  for (const row of incoming) {
    if (row.trade_id) byId.set(row.trade_id, row);
  }
  for (const row of accountTrades) {
    if (row.trade_id && !byId.has(row.trade_id)) byId.set(row.trade_id, row);
  }
  accountTrades = [...byId.values()]
    .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
    .slice(0, MAX_ACCOUNT_TRADES);
  accountTradesNotify.notify();
}

export function useLiveAccountTrades() {
  return useSyncExternalStore(subscribeAccountTrades, getAccountTrades, getAccountTrades);
}

export type AlgoLive = AlgoState;

const emptyBook: AlgoBook = { working: [], history: [] };
let algoBook: AlgoBook = emptyBook;
const algoListeners = new Set<() => void>();

export function resetLiveSession() {
  account = null;
  algoBook = emptyBook;
  accountNotify.notifyNow();
  algoListeners.forEach((fn) => fn());
}

export function subscribeAlgo(onChange: () => void) {
  algoListeners.add(onChange);
  return () => {
    algoListeners.delete(onChange);
  };
}

export function getAlgoBook(): AlgoBook {
  return algoBook;
}

function asBook(next: AlgoBook | AlgoState | null): AlgoBook {
  if (!next) return { working: [], history: [] };
  if (Array.isArray((next as AlgoBook).working)) {
    const book = next as AlgoBook;
    return {
      working: book.working.filter((a) => a.algo_id && algoIsWorking(a.status)),
      history: (book.history ?? []).filter((h) => h.algo_id),
    };
  }
  const one = next as AlgoState;
  const working = one.algo_id && algoIsWorking(one.status) ? [one] : [];
  return { working, history: [] };
}

export function setAlgo(next: AlgoBook | AlgoState | null) {
  algoBook = asBook(next);
  algoListeners.forEach((fn) => fn());
}

export function useLiveAlgos(): AlgoBook {
  return useSyncExternalStore(subscribeAlgo, getAlgoBook, getAlgoBook);
}

export interface LiquidationEvent {
  trade_id: string;
  market_index: number;
  symbol: string;
  kind: string;
  side: string | null;
  price: string;
  size: string;
  usd_amount: string | null;
  timestamp: number;
}

export type FeedHealth = {
  market_ws: "live" | "reconnecting" | "stale" | "down";
  account_ws: "live" | "reconnecting" | "stale" | "down";
  last_msg_at: number;
  account_last_msg_at: number;
  trade_subs: number;
  trade_subs_target: number;
  ts: number;
};

const MAX_LIQS = 500;
let liquidations: LiquidationEvent[] = [];
const liqNotify = makeThrottledNotify(100);

function liqTsMs(ts: number): number {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

/** Union by trade_id, always newest-first. */
function mergeLiquidations(
  existing: LiquidationEvent[],
  incoming: LiquidationEvent[]
): LiquidationEvent[] {
  if (!incoming.length) return existing;
  const byId = new Map<string, LiquidationEvent>();
  for (const row of existing) {
    if (row.trade_id) byId.set(liqIdentity(row.trade_id), row);
  }
  for (const row of incoming) {
    if (!row.trade_id) continue;
    const key = liqIdentity(row.trade_id);
    const prev = byId.get(key);
    if (!prev || liqTsMs(row.timestamp) >= liqTsMs(prev.timestamp)) {
      byId.set(key, row);
    }
  }
  return [...byId.values()]
    .sort((a, b) => liqTsMs(b.timestamp) - liqTsMs(a.timestamp))
    .slice(0, MAX_LIQS);
}

let feedHealth: FeedHealth = {
  market_ws: "down",
  account_ws: "down",
  last_msg_at: 0,
  account_last_msg_at: 0,
  trade_subs: 0,
  trade_subs_target: 0,
  ts: 0,
};
const healthListeners = new Set<() => void>();

export function subscribeLiquidations(onChange: () => void) {
  return liqNotify.subscribe(onChange);
}

export function getLiquidations() {
  return liquidations;
}

export function setLiquidations(next: LiquidationEvent[]) {
  liquidations = mergeLiquidations([], next);
  liqNotify.notifyNow();
}

/** Merge REST seed without wiping newer live rows already on screen. */
export function seedLiquidations(next: LiquidationEvent[]) {
  const merged = mergeLiquidations(liquidations, next);
  const same =
    merged.length === liquidations.length &&
    merged.every((row, i) => liqIdentity(row.trade_id) === liqIdentity(liquidations[i]?.trade_id));
  if (same) return;
  liquidations = merged;
  liqNotify.notifyNow();
}

export function prependLiquidations(incoming: LiquidationEvent[]) {
  if (!incoming.length) return;
  const before = liquidations;
  const merged = mergeLiquidations(before, incoming);
  const same =
    merged.length === before.length &&
    merged.every((row, i) => liqIdentity(row.trade_id) === liqIdentity(before[i]?.trade_id));
  if (same) return;
  liquidations = merged;
  liqNotify.notify();
}

export function useLiveLiquidations() {
  return useSyncExternalStore(subscribeLiquidations, getLiquidations, getLiquidations);
}

export type { AlertEvent };

const MAX_ALERTS = 150;
let alerts: AlertEvent[] = [];
const alertNotify = makeThrottledNotify(100);

function mergeAlerts(existing: AlertEvent[], incoming: AlertEvent[]): AlertEvent[] {
  if (!incoming.length) return existing;
  const byId = new Map<string, AlertEvent>();
  for (const row of existing) {
    if (row.id) byId.set(row.id, row);
  }
  for (const row of incoming) {
    if (!row.id) continue;
    const prev = byId.get(row.id);
    if (!prev || (row.ts || 0) >= (prev.ts || 0)) byId.set(row.id, row);
  }
  return [...byId.values()]
    .sort((a, b) => (b.ts || 0) - (a.ts || 0))
    .slice(0, MAX_ALERTS);
}

export function subscribeAlerts(onChange: () => void) {
  return alertNotify.subscribe(onChange);
}

export function getAlerts() {
  return alerts;
}

export function seedAlerts(next: AlertEvent[]) {
  const merged = mergeAlerts(alerts, next);
  const same =
    merged.length === alerts.length &&
    merged.every((row, i) => row.id === alerts[i]?.id);
  if (same) return;
  alerts = merged;
  alertNotify.notifyNow();
}

export function prependAlerts(incoming: AlertEvent[]) {
  if (!incoming.length) return;
  const before = alerts;
  const merged = mergeAlerts(before, incoming);
  const same =
    merged.length === before.length &&
    merged.every((row, i) => row.id === before[i]?.id);
  if (same) return;
  alerts = merged;
  alertNotify.notify();
}

export function useLiveAlerts() {
  return useSyncExternalStore(subscribeAlerts, getAlerts, getAlerts);
}

export function subscribeFeedHealth(onChange: () => void) {
  healthListeners.add(onChange);
  return () => {
    healthListeners.delete(onChange);
  };
}

export function getFeedHealth() {
  return feedHealth;
}

export function setFeedHealth(next: Partial<FeedHealth> & { type?: string }) {
  feedHealth = {
    market_ws: (next.market_ws as FeedHealth["market_ws"]) ?? feedHealth.market_ws,
    account_ws: (next.account_ws as FeedHealth["account_ws"]) ?? feedHealth.account_ws,
    last_msg_at: next.last_msg_at ?? feedHealth.last_msg_at,
    account_last_msg_at: next.account_last_msg_at ?? feedHealth.account_last_msg_at,
    trade_subs: next.trade_subs ?? feedHealth.trade_subs,
    trade_subs_target: next.trade_subs_target ?? feedHealth.trade_subs_target,
    ts: next.ts ?? Date.now(),
  };
  healthListeners.forEach((fn) => fn());
}

export function useFeedHealth() {
  return useSyncExternalStore(subscribeFeedHealth, getFeedHealth, getFeedHealth);
}

function flushLiveUi() {
  rollLiveCandles();
  tradesNotify.notifyNow();
  candle1sNotify.notifyNow();
  minuteCandleNotify.notifyNow();
  accountNotify.notifyNow();
  quoteNotify.notifyNow();
  liqNotify.notifyNow();
  alertNotify.notifyNow();
  accountTradesNotify.notifyNow();
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") flushLiveUi();
  });
}
