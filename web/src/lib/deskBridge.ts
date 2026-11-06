import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Market } from "@/lib/api";
import type { ChartDraft } from "@/lib/chartDraft";
import { requestChartDraftOpen, setChartDraft, setChartPlanArmed } from "@/lib/chartDraft";
import { WATCH_PATH } from "@/lib/deskRoute";
import type { MarketQuote } from "@/lib/liveData";
import { getMarketQuotes, subscribeQuoteDelta } from "@/lib/liveData";
import { notifyOk } from "@/lib/notify";
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
  | { type: "symbol"; symbol: string }
  | { type: "desk-ping" }
  | { type: "desk-pong" }
  | { type: "desk-symbol"; symbol: string }
  | { type: "idea-draft"; symbol: string; ideaId: string; draft: ChartDraft };

export function isDeskMessage(value: unknown): value is DeskMessage {
  if (!value || typeof value !== "object") return false;
  const row = value as {
    type?: unknown;
    symbol?: unknown;
    ideaId?: unknown;
    draft?: unknown;
    rows?: unknown;
    markets?: unknown;
    quotes?: unknown;
    samples?: unknown;
  };
  switch (row.type) {
    case "watch-hello":
    case "desk-closing":
    case "watch-closed":
    case "desk-ping":
    case "desk-pong":
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
    case "desk-symbol":
      return typeof row.symbol === "string" && Boolean(row.symbol);
    case "idea-draft":
      return typeof row.symbol === "string" && Boolean(row.symbol) && typeof row.ideaId === "string" && Boolean(row.ideaId) && isIdeaDraft(row.draft);
    default:
      return false;
  }
}

function isIdeaDraft(value: unknown): value is ChartDraft {
  if (!value || typeof value !== "object") return false;
  const row = value as { entry?: unknown; stop?: unknown; targets?: unknown; ladder?: unknown };
  const price = (n: unknown) => n == null || (typeof n === "number" && n > 0);
  if (!price(row.entry) || !price(row.stop)) return false;
  if (typeof row.entry !== "number" || typeof row.stop !== "number") return false;
  if (!Array.isArray(row.targets) || !row.targets.every(isDraftTarget)) return false;
  return isDraftLadder(row.ladder);
}

function isDraftTarget(target: unknown): boolean {
  if (!target || typeof target !== "object") return false;
  const item = target as { r?: unknown; pct?: unknown };
  return typeof item.r === "string" && typeof item.pct === "string";
}

function isDraftLadder(value: unknown): boolean {
  if (value == null) return true;
  if (!value || typeof value !== "object") return false;
  const ends = value as { from?: unknown; to?: unknown };
  return (
    typeof ends.from === "number" &&
    ends.from > 0 &&
    typeof ends.to === "number" &&
    ends.to > 0 &&
    ends.from !== ends.to
  );
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

const PONG_MS = 500;

function waitForDesk(ms = PONG_MS): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      unsub();
      resolve(ok);
    };
    const unsub = subscribeDesk((msg) => {
      if (msg.type === "desk-pong") finish(true);
    });
    const timer = window.setTimeout(() => finish(false), ms);
    postDesk({ type: "desk-ping" });
  });
}

/** Ping the desk tab. No pong within 500ms opens one tab with this Idea on the chart. */
export async function sendIdeaDraft(symbol: string, ideaId: string, draft: ChartDraft): Promise<"desk" | "tab"> {
  if (await waitForDesk()) {
    postDesk({ type: "idea-draft", symbol, ideaId, draft });
    return "desk";
  }
  window.open(`/${symbol}?idea=${encodeURIComponent(ideaId)}`, "_blank", "noopener");
  return "tab";
}

/** Switch the desk's Market. No Draft. No pong opens the Market in a new tab. */
export async function sendDeskSymbol(symbol: string): Promise<"desk" | "tab"> {
  if (await waitForDesk()) {
    postDesk({ type: "desk-symbol", symbol });
    return "desk";
  }
  window.open(`/${symbol}`, "_blank", "noopener");
  return "tab";
}

/** The desk answers Ideas: pong, switch Market, or take a Draft onto the chart. */
export function useDeskIdeasBridge({ onSymbol }: { onSymbol: (symbol: string) => void }) {
  const onSymbolRef = useRef(onSymbol);
  useEffect(() => {
    onSymbolRef.current = onSymbol;
  }, [onSymbol]);

  useEffect(() => {
    return subscribeDesk((msg) => {
      if (msg.type === "desk-ping") {
        postDesk({ type: "desk-pong" });
        return;
      }
      if (msg.type === "desk-symbol") {
        onSymbolRef.current(msg.symbol);
        return;
      }
      if (msg.type === "idea-draft") {
        const replaced = setChartDraft(msg.symbol, msg.draft, msg.ideaId);
        onSymbolRef.current(msg.symbol);
        if (replaced) notifyOk(`Draft replaced with the ${msg.symbol} Idea's plan`);
        setChartPlanArmed(true);
        requestChartDraftOpen(msg.symbol);
      }
    });
  }, []);
}
