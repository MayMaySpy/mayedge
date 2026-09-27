import type { Market, Position } from "@/lib/api";
import { parseDecimal } from "@/lib/numbers";

const CANONICAL_LEV = [1, 2, 4, 5, 8, 10, 16, 20, 25, 40, 50, 80, 100];

export const SLIP_KEY = "mayedge-slippage-pct";
export const SIZE_UNIT_KEY = "mayedge-size-unit";
export type SizeUnit = "base" | "usd";
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

export function loadSizeUnit(): SizeUnit {
  try {
    const v = localStorage.getItem(SIZE_UNIT_KEY);
    if (v === "usd" || v === "base") return v;
  } catch {
    /* ignore */
  }
  return "base";
}

export function persistSizeUnit(unit: SizeUnit) {
  try {
    localStorage.setItem(SIZE_UNIT_KEY, unit);
  } catch {
    /* ignore */
  }
}

/** Limit price when set; otherwise mid, live side, or last. */
export function ticketWorkingPrice(opts: {
  kind: OrderKind;
  priceNum: number;
  spot: number | null;
}): number | null {
  if (opts.kind === "limit" && opts.priceNum > 0) return opts.priceNum;
  return opts.spot;
}

export function baseToUsd(base: number, price: number | null): number {
  if (!(base > 0) || price == null || !(price > 0)) return 0;
  return base * price;
}

export function usdToBase(usd: number, price: number | null, decimals: number): number {
  if (!(usd > 0) || price == null || !(price > 0)) return 0;
  const d = Math.max(0, Math.min(decimals, 6));
  const f = 10 ** d;
  return Math.floor((usd / price) * f + 1e-9) / f;
}

export function formatUsdNotional(value: number): string {
  if (!(value > 0) || !Number.isFinite(value)) return "";
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatUsdRaw(value: number): string {
  if (!(value > 0) || !Number.isFinite(value)) return "";
  const s = value.toFixed(2);
  return s.replace(/\.?0+$/, "") || s;
}

export function ticketSizeFromInput(
  raw: string,
  unit: SizeUnit,
  price: number | null,
  decimals: number
): number {
  const n = parseDecimal(raw) ?? 0;
  if (n <= 0) return 0;
  if (unit === "base") return n;
  return usdToBase(n, price, decimals);
}

export function convertSizeOnUnitToggle(
  raw: string,
  from: SizeUnit,
  to: SizeUnit,
  price: number | null,
  decimals: number
): string {
  const n = parseDecimal(raw) ?? 0;
  if (n <= 0 || price == null || !(price > 0) || from === to) return raw;
  if (from === "base" && to === "usd") return formatUsdRaw(baseToUsd(n, price));
  if (from === "usd" && to === "base") return trimQty(usdToBase(n, price, decimals), decimals);
  return raw;
}

export function sizePctValue(
  pct: number,
  maxBase: number,
  unit: SizeUnit,
  price: number | null,
  decimals: number
): string {
  if (maxBase <= 0) return "";
  const base = (maxBase * pct) / 100;
  if (unit === "usd" && price != null && price > 0) {
    return formatUsdRaw(baseToUsd(base, price));
  }
  return trimQty(base, decimals);
}

/** Full close within one size step snaps to the live position. */
export function snapReduceOnlySize(
  sizeNum: number,
  absPos: number,
  decimals: number
): number {
  if (!(absPos > 0) || !(sizeNum > 0)) return sizeNum;
  const step = decimals >= 0 ? 10 ** -decimals : 0.01;
  if (Math.abs(sizeNum - absPos) <= step + 1e-9) return absPos;
  return Math.min(sizeNum, absPos);
}

export function sizeFieldOtherUnitHint(opts: {
  raw: string;
  unit: SizeUnit;
  symbol: string;
  price: number | null;
  decimals: number;
  sizeNum: number;
}): string | null {
  const typed = parseDecimal(opts.raw) ?? 0;
  if (typed <= 0 || opts.price == null || !(opts.price > 0)) return null;
  if (opts.unit === "usd") {
    const base = trimQty(opts.sizeNum, opts.decimals);
    return base ? `≈ ${base} ${opts.symbol}` : null;
  }
  const usd = formatUsdNotional(baseToUsd(opts.sizeNum, opts.price));
  return usd ? `≈ ${usd}` : null;
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
 * Lighter order-margin (cross): same-side needs notional/lev from free TAV
 * (USDC available + LTV of non-quote collateral); opposite-side credits 2×|pos|
 * notional before consuming free margin — so a full close+flip costs ~0 extra
 * margin, and max opposite = 2×|pos| + available×lev/price.
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

function formatMaxMinSize(
  base: number,
  unit: SizeUnit,
  symbol: string,
  decimals: number,
  price: number | null,
  prefix: "Max" | "Min"
): string {
  if (unit === "usd" && price != null && price > 0) {
    const usd = formatUsdNotional(base * price);
    return usd ? `${prefix} ${usd}` : `${prefix} ${trimQty(base, decimals)} ${symbol}`;
  }
  return `${prefix} ${trimQty(base, decimals)} ${symbol}`;
}

export function ticketBlockReason(opts: {
  tradingEnabled: boolean;
  feedReady: boolean;
  feedReason?: string | null;
  sizeNum: number;
  sizeRaw?: string;
  sizeUnit?: SizeUnit;
  workingPrice?: number | null;
  maxSize?: number;
  symbol: string;
  decimals: number;
  kind: OrderKind;
  price: string;
  isMaker: boolean;
  minSz: number;
  algoBlocked?: string | null;
}): string | null {
  const unit = opts.sizeUnit ?? "base";
  const px = opts.workingPrice ?? null;
  const typed = parseDecimal(opts.sizeRaw ?? "") ?? 0;

  if (!opts.tradingEnabled) return "Trading not configured";
  if (!opts.feedReady) return opts.feedReason ?? "Feed not ready";
  if (unit === "usd" && (px == null || !(px > 0)) && typed > 0) return "No price";
  if (opts.sizeNum <= 0) return "Enter size";
  if (opts.maxSize != null && opts.maxSize > 0 && opts.sizeNum > opts.maxSize + 1e-9) {
    return formatMaxMinSize(opts.maxSize, unit, opts.symbol, opts.decimals, px, "Max");
  }
  if (opts.kind === "limit" && !opts.price) return "Enter price";
  if (opts.isMaker && opts.minSz > 0 && opts.sizeNum + 1e-9 < opts.minSz) {
    return formatMaxMinSize(opts.minSz, unit, opts.symbol, opts.decimals, px, "Min");
  }
  if (opts.kind === "algo" && opts.algoBlocked) return opts.algoBlocked;
  return null;
}
