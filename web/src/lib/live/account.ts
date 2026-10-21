/** Live account data: the account, its trades, its algos, Auto kill and open Realized. */
import { useSyncExternalStore } from "react";
import type { Account, AccountTrade, AlgoBook, AlgoState } from "@/lib/api";
import { algoIsWorking } from "@/lib/algos";
import type { OpenTripRealized } from "@/lib/api.gen";
import { makeThrottledNotify } from "@/lib/live/notify";

const accountNotify = makeThrottledNotify(150);

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
  const hasAssets = Object.prototype.hasOwnProperty.call(next, "assets");
  account = {
    collateral: preferBalance(prev?.collateral, next.collateral),
    available: preferBalance(prev?.available, next.available),
    trade_available: preferBalance(prev?.trade_available, next.trade_available),
    portfolio_margin: preferBalance(prev?.portfolio_margin, next.portfolio_margin),
    unrealized_pnl: next.unrealized_pnl ?? prev?.unrealized_pnl ?? "0",
    positions: hasPositions ? (next.positions ?? []) : (prev?.positions ?? []),
    open_orders: hasOrders ? (next.open_orders ?? []) : (prev?.open_orders ?? []),
    assets: hasAssets ? (next.assets ?? []) : (prev?.assets ?? []),
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

/** An open Round trip's Realized, from the journal (journal-rules, On a Position). */
export type { OpenTripRealized };

let journalOpen: OpenTripRealized[] = [];
const journalOpenListeners = new Set<() => void>();

export function subscribeJournalOpen(onChange: () => void) {
  journalOpenListeners.add(onChange);
  return () => {
    journalOpenListeners.delete(onChange);
  };
}

export function getJournalOpen() {
  return journalOpen;
}

export function setJournalOpen(rows: OpenTripRealized[]) {
  journalOpen = rows;
  journalOpenListeners.forEach((fn) => fn());
}

export function useJournalOpen() {
  return useSyncExternalStore(subscribeJournalOpen, getJournalOpen, getJournalOpen);
}

export interface LiveAutoKill {
  armed: boolean;
  loss_usd: number | null;
  profit_usd: number | null;
  fired_at: number | null;
  fired_reason: string | null;
  fired_upnl: number | null;
  last_kill_status: string | null;
}

const defaultAutoKill: LiveAutoKill = {
  armed: false,
  loss_usd: null,
  profit_usd: null,
  fired_at: null,
  fired_reason: null,
  fired_upnl: null,
  last_kill_status: null,
};

let autoKillState: LiveAutoKill = defaultAutoKill;
const autoKillListeners = new Set<() => void>();

export function subscribeAutoKill(onChange: () => void) {
  autoKillListeners.add(onChange);
  return () => {
    autoKillListeners.delete(onChange);
  };
}

export function getAutoKill() {
  return autoKillState;
}

export function setAutoKill(next: Partial<LiveAutoKill> & { type?: string }) {
  autoKillState = {
    armed: next.armed ?? autoKillState.armed,
    loss_usd: next.loss_usd !== undefined ? next.loss_usd : autoKillState.loss_usd,
    profit_usd: next.profit_usd !== undefined ? next.profit_usd : autoKillState.profit_usd,
    fired_at: next.fired_at !== undefined ? next.fired_at : autoKillState.fired_at,
    fired_reason: next.fired_reason !== undefined ? next.fired_reason : autoKillState.fired_reason,
    fired_upnl: next.fired_upnl !== undefined ? next.fired_upnl : autoKillState.fired_upnl,
    last_kill_status:
      next.last_kill_status !== undefined ? next.last_kill_status : autoKillState.last_kill_status,
  };
  autoKillListeners.forEach((fn) => fn());
}

export function useAutoKill() {
  return useSyncExternalStore(subscribeAutoKill, getAutoKill, getAutoKill);
}

/** Deliver every held account notice now, e.g. when the tab comes back. */
export function flushAccountUi() {
  accountNotify.notifyNow();
  accountTradesNotify.notifyNow();
}
