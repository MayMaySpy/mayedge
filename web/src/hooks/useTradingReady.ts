import { useSyncExternalStore } from "react";
import {
  getFeedHealth,
  isBookSynced,
  subscribeBook,
  subscribeFeedHealth,
} from "@/lib/liveData";

export interface TradingReadyInput {
  connected: boolean;
}

export interface TradingReady {
  ready: boolean;
  reason: string | null;
}

const SNAP = {
  reconnecting: { ready: false, reason: "Reconnecting" },
  stale: { ready: false, reason: "Feed stale" },
  down: { ready: false, reason: "Feed down" },
  feedReconnect: { ready: false, reason: "Feed reconnecting" },
  syncing: { ready: false, reason: "Book syncing" },
  accountStale: { ready: false, reason: "Account feed stale" },
  accountDown: { ready: false, reason: "Account feed down" },
  accountReconnect: { ready: false, reason: "Account reconnecting" },
  ready: { ready: true, reason: null },
} as const satisfies Record<string, TradingReady>;

function subscribeTradingReady(onChange: () => void) {
  const a = subscribeFeedHealth(onChange);
  const b = subscribeBook(onChange);
  return () => {
    a();
    b();
  };
}

/** Cached snapshots — useSyncExternalStore loops if getSnapshot returns a new object. */
export function getTradingReadySnapshot(connected: boolean): TradingReady {
  if (!connected) return SNAP.reconnecting;
  const health = getFeedHealth();
  if (health.market_ws !== "live") {
    if (health.market_ws === "stale") return SNAP.stale;
    if (health.market_ws === "down") return SNAP.down;
    return SNAP.feedReconnect;
  }
  if (!isBookSynced()) return SNAP.syncing;
  if (health.account_ws !== "live") {
    if (health.account_ws === "stale") return SNAP.accountStale;
    if (health.account_ws === "down") return SNAP.accountDown;
    return SNAP.accountReconnect;
  }
  return SNAP.ready;
}

export function useTradingReady(input: TradingReadyInput) {
  const connected = input.connected;
  return useSyncExternalStore(
    subscribeTradingReady,
    () => getTradingReadySnapshot(connected),
    () => getTradingReadySnapshot(connected)
  );
}
