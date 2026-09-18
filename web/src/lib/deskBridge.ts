import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Market } from "@/lib/api";
import { WATCH_PATH } from "@/lib/deskRoute";
import type { MarketQuote } from "@/lib/liveData";
import { getMarketQuotes, subscribeQuoteDelta } from "@/lib/liveData";
import type { PriceSample } from "@/lib/watchPath";
import { replaceWatchSamples, snapshotWatchSamples } from "@/lib/watchSamples";

export const WATCH_WINDOW_NAME = "mayedge-watch";
const CHANNEL = "mayedge-desk";

export type DeskMessage =
  | { type: "watch-hello" }
  | { type: "watch-closed"; samples?: Record<string, PriceSample[]> }
  | { type: "desk-closing" }
  | {
      type: "desk-state";
      markets: Market[];
      quotes: MarketQuote[];
      samples: Record<string, PriceSample[]>;
      symbol: string;
    }
  | { type: "quotes"; rows: MarketQuote[] }
  | { type: "markets"; markets: Market[] }
  | { type: "symbol"; symbol: string };

export function isDeskMessage(value: unknown): value is DeskMessage {
  if (!value || typeof value !== "object") return false;
  const row = value as {
    type?: unknown;
    symbol?: unknown;
    rows?: unknown;
    markets?: unknown;
    quotes?: unknown;
    samples?: unknown;
  };
  switch (row.type) {
    case "watch-hello":
    case "desk-closing":
    case "watch-closed":
      return true;
    case "desk-state":
      return (
        Array.isArray(row.markets) &&
        Array.isArray(row.quotes) &&
        typeof row.samples === "object" &&
        row.samples != null &&
        typeof row.symbol === "string"
      );
    case "quotes":
      return Array.isArray(row.rows);
    case "markets":
      return Array.isArray(row.markets);
    case "symbol":
      return typeof row.symbol === "string" && Boolean(row.symbol);
    default:
      return false;
  }
}

let chan: BroadcastChannel | null | undefined;
let popped = false;
const poppedListeners = new Set<() => void>();

function setPopped(next: boolean) {
  if (popped === next) return;
  popped = next;
  poppedListeners.forEach((fn) => fn());
}

export function isWatchPopped() {
  return popped;
}

export function subscribeWatchPopped(onChange: () => void) {
  poppedListeners.add(onChange);
  return () => {
    poppedListeners.delete(onChange);
  };
}

export function useWatchPopped() {
  return useSyncExternalStore(subscribeWatchPopped, isWatchPopped, () => false);
}

function getChannel(): BroadcastChannel | null {
  if (chan !== undefined) return chan;
  try {
    chan = new BroadcastChannel(CHANNEL);
  } catch {
    chan = null;
  }
  return chan;
}

export function postDesk(msg: DeskMessage) {
  try {
    getChannel()?.postMessage(msg);
  } catch {
    /* closed */
  }
}

export function subscribeDesk(onMsg: (msg: DeskMessage) => void) {
  const ch = getChannel();
  if (!ch) return () => {};
  const handler = (ev: MessageEvent) => {
    if (isDeskMessage(ev.data)) onMsg(ev.data);
  };
  ch.addEventListener("message", handler);
  return () => ch.removeEventListener("message", handler);
}

export function openWatchWindow(): Window | null {
  try {
    const w = window.open(WATCH_PATH, WATCH_WINDOW_NAME);
    if (w) setPopped(true);
    return w;
  } catch {
    return null;
  }
}

function postDeskState(markets: readonly Market[], symbol: string) {
  postDesk({
    type: "desk-state",
    markets: [...markets],
    quotes: Object.values(getMarketQuotes()),
    samples: snapshotWatchSamples(),
    symbol,
  });
}

export function useDeskWatchBridge({
  markets,
  symbol,
  onSymbol,
}: {
  markets: readonly Market[];
  symbol: string;
  onSymbol: (symbol: string) => void;
}) {
  const marketsRef = useRef(markets);
  const symbolRef = useRef(symbol);
  const onSymbolRef = useRef(onSymbol);

  useEffect(() => {
    marketsRef.current = markets;
  }, [markets]);
  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);
  useEffect(() => {
    onSymbolRef.current = onSymbol;
  }, [onSymbol]);

  useEffect(() => {
    const unsubDesk = subscribeDesk((msg) => {
      if (msg.type === "watch-hello") {
        setPopped(true);
        postDeskState(marketsRef.current, symbolRef.current);
        return;
      }
      if (msg.type === "watch-closed") {
        if (msg.samples) replaceWatchSamples(msg.samples);
        setPopped(false);
        return;
      }
      if (msg.type === "symbol") onSymbolRef.current(msg.symbol);
    });

    const unsubQuotes = subscribeQuoteDelta((rows) => {
      if (!popped) return;
      postDesk({ type: "quotes", rows });
    });

    const onUnload = () => postDesk({ type: "desk-closing" });
    window.addEventListener("pagehide", onUnload);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      unsubDesk();
      unsubQuotes();
      window.removeEventListener("pagehide", onUnload);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, []);

  useEffect(() => {
    if (!isWatchPopped()) return;
    postDesk({ type: "markets", markets: [...markets] });
  }, [markets]);

  useEffect(() => {
    if (!isWatchPopped()) return;
    postDesk({ type: "symbol", symbol });
  }, [symbol]);
}
