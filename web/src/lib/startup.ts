/**
 * Desk load order: the selected Market's chart candles are asked for first and drawn
 * first. Every other startup fetch waits for `chartDrawn()` (or a fallback timer), so it
 * neither queues ahead of the candles nor competes with the chart's first paint.
 */
import { useSyncExternalStore } from "react";

import { api, ApiError, type Candle } from "@/lib/api";
import { loadMode } from "@/components/widgets/chart/chartPrefs";
import { isIdeasPath, isJournalPath, isPortfolioPath, isWatchPath, readSymbol } from "@/lib/deskRoute";
import { candleSource, loadTimeframe, parseTimeframe } from "@/lib/timeframe";

/** Past this, the rest of the desk loads even if the chart never drew. */
export const STARTUP_FALLBACK_MS = 3000;
const PAINT_WAIT_MS = 100;

/** Open unless startDesk() closed it for a desk load, so other pages and tests never wait. */
let drawn = true;
let marked = false;
let fallback: ReturnType<typeof setTimeout> | null = null;
const waiting = new Set<() => void>();
const listeners = new Set<() => void>();

/**
 * The chart has handed its first candles to the series (or will not draw any). The rest
 * is released after that frame paints; a hidden tab never paints, so the fallback covers it.
 */
export function chartDrawn(): void {
  if (drawn || marked) return;
  marked = true;
  performance.mark?.("mayedge:chart-drawn");
  // After the next paint, or PAINT_WAIT_MS where frames are paused (an occluded window).
  let sent = false;
  const go = () => {
    if (sent) return;
    sent = true;
    setTimeout(release, 0);
  };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(go);
  setTimeout(go, PAINT_WAIT_MS);
}

function release() {
  if (drawn) return;
  drawn = true;
  performance.mark?.("mayedge:desk-released");
  if (fallback != null) clearTimeout(fallback);
  fallback = null;
  for (const listener of listeners) listener();
  // One macrotask per caller, after the chart's paint, so the queue never stacks into one long task.
  for (const run of [...waiting]) {
    setTimeout(() => {
      if (!waiting.delete(run)) return;
      run();
    }, 0);
  }
}

export function isChartDrawn(): boolean {
  return drawn;
}

/** Run now if the chart has drawn, else once it does. The returned function cancels a wait. */
export function afterChart(run: () => void): () => void {
  if (drawn) {
    run();
    return () => {};
  }
  waiting.add(run);
  return () => {
    waiting.delete(run);
  };
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

/** True once the rest of the desk may load. Gate a startup effect on it. */
export function useAfterChart(): boolean {
  return useSyncExternalStore(subscribe, isChartDrawn, () => true);
}

/** How long an answered candle request still serves a caller asking for the same thing. */
const REUSE_MS = 5000;
const recent = new Map<string, { req: Promise<Candle[]>; at: number | null }>();

/**
 * One request per Market, resolution and count: callers while it is out, or within
 * REUSE_MS of its answer, share it. The prefetch and the chart's first ask meet here.
 */
export function loadCandles(symbol: string, resolution: string, count: number): Promise<Candle[]> {
  const key = `${symbol.toUpperCase()}:${resolution}:${count}`;
  const now = Date.now();
  for (const [k, e] of recent) if (e.at != null && now - e.at >= REUSE_MS) recent.delete(k);
  const hit = recent.get(key);
  if (hit) return hit.req;
  const entry: { req: Promise<Candle[]>; at: number | null } = { req: Promise.resolve([]), at: null };
  entry.req = api.candles(symbol, resolution, count).then(
    (rows) => {
      entry.at = Date.now();
      return rows;
    },
    (err: unknown) => {
      if (recent.get(key) === entry) recent.delete(key);
      throw err;
    },
  );
  recent.set(key, entry);
  return entry.req;
}

/** Waits between history attempts; the last repeats until the history arrives. */
export const HISTORY_RETRY_MS = [1000, 2000, 4000, 8000, 15000] as const;

/** The desk's read budget refusal says when to come back: "… retry shortly (3s)". */
export function retryHintMs(err: unknown): number {
  if (!(err instanceof ApiError) || err.status !== 429) return 0;
  const m = /\((\d+(?:\.\d+)?)s\)/.exec(err.message);
  return m ? Math.ceil(parseFloat(m[1]) * 1000) : 0;
}

/**
 * Ask until it answers. A refused or failed history ask is not "no history": the desk's
 * read budget turns chart reads away with a 429 when it is spent, and a chart that took
 * that as empty showed only the live bar it built from the trade feed.
 * The returned function stops it.
 */
export function untilLoaded<T>(
  load: () => Promise<T>,
  onLoad: (value: T) => void,
  onFail?: (err: unknown) => void,
): () => void {
  let stopped = false;
  let tries = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const attempt = () => {
    load().then(
      (value) => {
        if (!stopped) onLoad(value);
      },
      (err: unknown) => {
        if (stopped) return;
        onFail?.(err);
        const backoff = HISTORY_RETRY_MS[Math.min(tries, HISTORY_RETRY_MS.length - 1)];
        tries += 1;
        timer = setTimeout(attempt, Math.max(backoff, retryHintMs(err)));
      },
    );
  };
  attempt();
  return () => {
    stopped = true;
    if (timer != null) clearTimeout(timer);
  };
}

/** The chart's first request, as the chart will make it, sent before React renders. */
export function deskFirstCandles(
  pathname: string,
  mode: string,
  tf: string,
): { symbol: string; resolution: string; count: number } | null {
  if (isWatchPath(pathname) || isJournalPath(pathname) || isPortfolioPath(pathname) || isIdeasPath(pathname)) {
    return null;
  }
  if (mode !== "price") return null;
  const bar = parseTimeframe(tf) ?? parseTimeframe("1m")!;
  const resolution = candleSource(bar);
  return { symbol: readSymbol(pathname), resolution, count: resolution === "1s" ? 3600 : 500 };
}

/** Called once from main.tsx: on a desk load, ask for the chart's candles and hold the rest until they draw. */
export function startDesk(): void {
  const first = deskFirstCandles(window.location.pathname, loadMode(), loadTimeframe());
  if (!first) return;
  drawn = false;
  void loadCandles(first.symbol, first.resolution, first.count).catch(() => {});
  fallback = setTimeout(release, STARTUP_FALLBACK_MS);
}
