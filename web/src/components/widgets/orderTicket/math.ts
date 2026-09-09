import type { Market, Position } from "@/lib/api";

const CANONICAL_LEV = [1, 2, 4, 5, 8, 10, 16, 20, 25, 40, 50, 80, 100];

export const SLIP_KEY = "mayedge-slippage-pct";
export const SLIP_PRESETS = [0.2, 0.5, 1, 2];
export const SIZE_PCTS = [25, 50, 75, 100];
export const TIF_CHIPS = [
  { id: "gtt", label: "Resting", hint: "Good till time — rests on the book" },
  { id: "ioc", label: "IOC", hint: "Immediate or cancel — take liquidity now" },
  { id: "post_only", label: "Post", hint: "Post only — maker; rejects if it would take" },
] as const;

export const ORDER_KINDS = [
  { id: "market", label: "Market" },
  { id: "limit", label: "Limit" },
  { id: "algo", label: "Algo" },
] as const;

export type OrderKind = (typeof ORDER_KINDS)[number]["id"];

export function leveragePresets(market: {
  max_leverage?: number;
  allowed_leverages?: number[];
}): number[] {
  if (market.allowed_leverages?.length) return market.allowed_leverages;
  const max = market.max_leverage ?? 20;
  const out = CANONICAL_LEV.filter((x) => x <= max);
  return out.length ? out : [1];
}

export function snapLeverage(allowed: number[], raw: string): number | null {
  const x = parseInt(raw, 10);
  if (!Number.isFinite(x) || x < 1) return null;
  return allowed.reduce((best, n) => {
    const dn = Math.abs(n - x);
    const db = Math.abs(best - x);
    if (dn < db) return n;
    if (dn === db && n < best) return n;
    return best;
  });
}

/** min, lower-quartile, upper-quartile, max — snapped to allowed leverages. */
export function leverageAnchors(allowed: number[]): number[] {
  if (allowed.length <= 4) return allowed;
  const min = allowed[0];
  const max = allowed[allowed.length - 1];
  const span = max - min;
  const low = snapLeverage(allowed, String(min + span * 0.25)) ?? min;
  const high = snapLeverage(allowed, String(min + span * 0.75)) ?? max;
  const out: number[] = [min];
  for (const x of [low, high, max]) {
    if (!out.includes(x)) out.push(x);
  }
  if (out.length < 4) {
    for (const x of allowed) {
      if (out.includes(x)) continue;
      out.splice(out.length - 1, 0, x);
      if (out.length >= 4) break;
    }
  }
  return out;
}

export function suggestedLeverage(market: Market, positions: Position[] | undefined): string {
  const presets = leveragePresets(market);
  const maxLev = presets[presets.length - 1] ?? market.max_leverage ?? 20;
  const defLev = market.default_leverage ?? maxLev;
  const snapped = presets.includes(defLev) ? defLev : maxLev;
  const pos = positions?.find((p) => p.market_index === market.market_index);
  if (!pos?.leverage) return String(snapped);
  const nearest = presets.reduce(
    (best, x) => (Math.abs(x - pos.leverage) < Math.abs(best - pos.leverage) ? x : best),
    snapped
  );
  return String(nearest);
}

export function chaseBandDefaults(_market: Market): { floor: string; ceiling: string } {
  return { floor: "", ceiling: "" };
}

/** Working range chips from mid — user must set band before starting chase. */
export function chaseBandFromPct(
  market: Market,
  pct: number,
  mid?: number | null
): { floor: string; ceiling: string } {
  const px = mid ?? market.last_trade_price ?? market.mark_price;
  if (!px || px <= 0 || !(pct > 0)) return { floor: "", ceiling: "" };
  const d = Math.max(0, market.price_decimals ?? 2);
  const fmt = (n: number) => n.toFixed(d).replace(/\.?0+$/, "");
  const lo = px * (1 - pct / 100);
  const hi = px * (1 + pct / 100);
  return { floor: fmt(lo), ceiling: fmt(hi) };
}

export const CHASE_BAND_PCTS = [0.5, 1, 2] as const;

export function loadSlipPct(): string {
  try {
    const n = parseFloat(localStorage.getItem(SLIP_KEY) ?? "");
    if (Number.isFinite(n) && n > 0 && n <= 50) return String(n);
  } catch {
    /* ignore */
  }
  return "1";
}

export function persistSlipPct(raw: string) {
  const n = parseFloat(raw);
  if (!Number.isFinite(n) || n <= 0) return;
  try {
    localStorage.setItem(SLIP_KEY, String(n));
  } catch {
    /* ignore */
  }
}

export function trimQty(n: number, decimals: number): string {
  if (!Number.isFinite(n) || n <= 0) return "";
  const d = Math.max(0, Math.min(decimals, 6));
  const f = 10 ** d;
  const q = Math.floor(n * f + 1e-9) / f;
  if (q <= 0) return "";
  return q.toFixed(d).replace(/\.?0+$/, "") || "0";
}

export function makerMinSize(minBase: number, minQuote: number, price: number | null): number {
  let floor = minBase > 0 ? minBase : 0;
  if (price && price > 0 && minQuote > 0) floor = Math.max(floor, minQuote / price);
  return floor;
}

/** Ticket hint for venue min size. Warns once a typed qty is below the floor. */
export function minSizeHint(
  minSz: number,
  decimals: number,
  valueNum: number
): { text: string; warn: boolean } | null {
  if (!(minSz > 0)) return null;
  const min = trimQty(minSz, decimals);
  if (!min) return null;
  const below = valueNum > 0 && valueNum + 1e-9 < minSz;
  return below ? { text: `Below min ${min}`, warn: true } : { text: `min ${min}`, warn: false };
}

/**
 * Max base size the ticket can send.
 *
 * Lighter order-margin (cross): same-side needs notional/lev from free balance;
 * opposite-side credits 2×|pos| notional before consuming free margin — so a full
 * close+flip costs ~0 extra margin, and max opposite = 2×|pos| + available×lev/price.
 */
export function maxOrderSize(opts: {
  available: number;
  leverage: number;
  price: number | null;
  /** Signed position: long > 0, short < 0. */
  signedPos: number;
  side: "buy" | "sell";
  reduceOnly: boolean;
}): number {
  const absPos = Math.abs(opts.signedPos);
  if (opts.reduceOnly) return absPos > 0 ? absPos : 0;
  const px = opts.price;
  if (px == null || !(px > 0) || !(opts.leverage > 0)) return 0;
  const fromMargin = opts.available > 0 ? (opts.available * opts.leverage) / px : 0;
  const opposite =
    (opts.side === "buy" && opts.signedPos < 0) || (opts.side === "sell" && opts.signedPos > 0);
  return opposite ? fromMargin + 2 * absPos : fromMargin;
}

export function ticketBlockReason(opts: {
  tradingEnabled: boolean;
  feedReady: boolean;
  feedReason?: string | null;
  sizeNum: number;
  maxSize?: number;
  symbol: string;
  decimals: number;
  kind: OrderKind;
  price: string;
  isMaker: boolean;
  minSz: number;
  algo: string;
  twapSec: number | null;
  twapSlip?: number | null;
  floorNum: number;
  ceilNum: number;
  clipNum: number;
  twapAdvanced?: boolean;
  twapFreqSec?: number | null;
}): string | null {
  if (!opts.tradingEnabled) return "Trading not configured";
  if (!opts.feedReady) return opts.feedReason ?? "Feed not ready";
  if (opts.sizeNum <= 0) return "Enter size";
  if (opts.maxSize != null && opts.maxSize > 0 && opts.sizeNum > opts.maxSize + 1e-9) {
    return `Max ${trimQty(opts.maxSize, opts.decimals)} ${opts.symbol}`;
  }
  if (opts.kind === "limit" && !opts.price) return "Enter price";
  if (opts.isMaker && opts.minSz > 0 && opts.sizeNum + 1e-9 < opts.minSz) {
    return `Min ${trimQty(opts.minSz, opts.decimals)} ${opts.symbol}`;
  }
  if (opts.kind === "algo" && opts.algo === "twap" && opts.twapSec == null) {
    return "Running time 1m–30d";
  }
  if (
    opts.kind === "algo" &&
    opts.algo === "twap" &&
    opts.twapAdvanced &&
    (opts.twapFreqSec == null || opts.twapFreqSec < 2 || opts.twapFreqSec > 3600)
  ) {
    return "Slice 2s–1h";
  }
  if (
    opts.kind === "algo" &&
    opts.algo === "twap" &&
    !opts.twapAdvanced &&
    opts.twapSlip != null &&
    opts.twapSlip > 0.05 + 1e-9
  ) {
    return "Max 5% from mark";
  }
  if (
    opts.kind === "algo" &&
    opts.algo === "chase-iceberg" &&
    (!(opts.floorNum > 0) || !(opts.ceilNum > opts.floorNum))
  ) {
    return "Set floor / ceiling";
  }
  if (opts.kind === "algo" && opts.algo === "chase-iceberg") {
    if (opts.minSz > 0 && opts.sizeNum + 1e-9 < opts.minSz) {
      return `Min ${trimQty(opts.minSz, opts.decimals)} ${opts.symbol}`;
    }
    if (!(opts.clipNum > 0) || opts.clipNum > opts.sizeNum + 1e-9) {
      return opts.clipNum <= 0 ? "Enter clip size" : "Clip exceeds parent";
    }
    if (opts.minSz > 0 && opts.clipNum + 1e-9 < opts.minSz) {
      return `Min ${trimQty(opts.minSz, opts.decimals)} ${opts.symbol}`;
    }
  }
  return null;
}

export function orderCta(opts: {
  kind: OrderKind;
  algo: string;
  side: "buy" | "sell";
  base: string;
}): string {
  if (opts.kind === "algo" && opts.algo === "chase-iceberg") {
    return opts.side === "buy" ? "Chase buy" : "Chase sell";
  }
  if (opts.kind === "algo" && opts.algo === "twap") {
    return opts.side === "buy" ? "TWAP buy" : "TWAP sell";
  }
  return opts.side === "buy" ? "Buy" : "Sell";
}
