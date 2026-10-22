/** Live boards: liquidations, alerts, Scan, the feed status and the send budget. */
import { useSyncExternalStore } from "react";
import type {
  AlertEvent,
  FundingExtremeRow,
  LiquidationEvent,
  ScanActivityRow,
  ToneBoardRow,
} from "@/lib/api";
import { liqIdentity } from "@/lib/venuePair";
import { makeThrottledNotify } from "@/lib/live/notify";

export type { LiquidationEvent };


export type FeedHealth = {
  market_ws: "live" | "reconnecting" | "stale" | "down";
  account_ws: "live" | "reconnecting" | "stale" | "down";
  last_msg_at: number;
  account_last_msg_at: number;
  trade_subs: number;
  trade_subs_target: number;
  /** Ms since Lighter itself went offline (503, service restart); 0 when it answers. */
  venue_down_since: number;
  venue_down_reason: string | null;
  ts: number;
};

const MAX_LIQS = 500;
let liquidations: LiquidationEvent[] = [];
const liqNotify = makeThrottledNotify(100);

function liqTsMs(ts: number): number {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

function liqSig(row: LiquidationEvent): string {
  return `${liqIdentity(row.trade_id)}:${row.size}:${row.usd_amount ?? ""}:${row.fill_count ?? 0}:${row.timestamp}`;
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
    if (!prev) {
      byId.set(key, row);
      continue;
    }
    const prevCount = prev.fill_count ?? 1;
    const nextCount = row.fill_count ?? 1;
    if (nextCount !== prevCount) {
      if (nextCount > prevCount) byId.set(key, row);
      continue;
    }
    if (liqTsMs(row.timestamp) >= liqTsMs(prev.timestamp)) {
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
  venue_down_since: 0,
  venue_down_reason: null,
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
    merged.every((row, i) => liqSig(row) === liqSig(liquidations[i]!));
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
    merged.every((row, i) => liqSig(row) === liqSig(before[i]!));
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

let scanActivity: ScanActivityRow[] = [];
const activityNotify = makeThrottledNotify(100);

export function subscribeScanActivity(onChange: () => void) {
  return activityNotify.subscribe(onChange);
}

export function getScanActivity() {
  return scanActivity;
}

export function setScanActivity(rows: ScanActivityRow[]) {
  scanActivity = rows;
  activityNotify.notify();
}

export function useScanActivity() {
  return useSyncExternalStore(subscribeScanActivity, getScanActivity, getScanActivity);
}

let fundingExtremes: FundingExtremeRow[] = [];
const fundingNotify = makeThrottledNotify(100);

export function subscribeFundingExtremes(onChange: () => void) {
  return fundingNotify.subscribe(onChange);
}

export function getFundingExtremes() {
  return fundingExtremes;
}

export function setFundingExtremes(rows: FundingExtremeRow[]) {
  fundingExtremes = rows;
  fundingNotify.notify();
}

export function useFundingExtremes() {
  return useSyncExternalStore(subscribeFundingExtremes, getFundingExtremes, getFundingExtremes);
}

let toneBoard: ToneBoardRow[] = [];
const toneNotify = makeThrottledNotify(100);

export function subscribeToneBoard(onChange: () => void) {
  return toneNotify.subscribe(onChange);
}

export function getToneBoard() {
  return toneBoard;
}

export function setToneBoard(rows: ToneBoardRow[]) {
  toneBoard = rows;
  toneNotify.notify();
}

export function useToneBoard() {
  return useSyncExternalStore(subscribeToneBoard, getToneBoard, getToneBoard);
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
    venue_down_since: next.venue_down_since ?? feedHealth.venue_down_since,
    venue_down_reason:
      next.venue_down_reason !== undefined ? next.venue_down_reason : feedHealth.venue_down_reason,
    ts: next.ts ?? Date.now(),
  };
  healthListeners.forEach((fn) => fn());
}

export function useFeedHealth() {
  return useSyncExternalStore(subscribeFeedHealth, getFeedHealth, getFeedHealth);
}

export type SendBudget = {
  requests: number;
  requests_cap: number;
  tx: number;
  tx_cap: number;
  algo_tx_cap: number;
  cooling_until: number;
  refused_60s: number;
};

const emptyBudget: SendBudget = {
  requests: 0,
  requests_cap: 54,
  tx: 0,
  tx_cap: 38,
  algo_tx_cap: 30,
  cooling_until: 0,
  refused_60s: 0,
};

let sendBudget: SendBudget = emptyBudget;
const budgetListeners = new Set<() => void>();

export function subscribeSendBudget(onChange: () => void) {
  budgetListeners.add(onChange);
  return () => {
    budgetListeners.delete(onChange);
  };
}

export function getSendBudget() {
  return sendBudget;
}

export function setSendBudget(next: Partial<SendBudget> & { type?: string }) {
  sendBudget = {
    requests: next.requests ?? sendBudget.requests,
    requests_cap: next.requests_cap ?? sendBudget.requests_cap,
    tx: next.tx ?? sendBudget.tx,
    tx_cap: next.tx_cap ?? sendBudget.tx_cap,
    algo_tx_cap: next.algo_tx_cap ?? sendBudget.algo_tx_cap,
    cooling_until: next.cooling_until ?? sendBudget.cooling_until,
    refused_60s: next.refused_60s ?? sendBudget.refused_60s,
  };
  budgetListeners.forEach((fn) => fn());
}

export function useSendBudget() {
  return useSyncExternalStore(subscribeSendBudget, getSendBudget, getSendBudget);
}

/** Deliver every held board notice now, e.g. when the tab comes back. */
export function flushBoardsUi() {
  liqNotify.notifyNow();
  alertNotify.notifyNow();
}
