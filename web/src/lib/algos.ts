import { parseDecimal } from "@/lib/numbers";
import type { Market } from "@/lib/api";

export type AlgoId = "twap" | "chase-iceberg";

export interface AlgoDef {
  id: AlgoId;
  label: string;
  /** One-line job. Shown under the picker before params. */
  intent: string;
}

/** Add a row here, then a sheet under `orderTicket/kinds/AlgoParams`. Shared size/side/RO stay on the ticket. */
export const ALGOS: readonly AlgoDef[] = [
  { id: "twap", label: "TWAP", intent: "Time-weighted slices over the running time" },
  {
    id: "chase-iceberg",
    label: "Chase",
    intent: "Passive clips behind the touch — chase, never cross",
  },
];

export const TWAP_SLICE_SECONDS = 30;
export const TWAP_MIN_SECONDS = 60;
export const TWAP_MAX_SECONDS = 30 * 24 * 60 * 60;
export const TWAP_MAX_PRICE_PCTS = [0.1, 0.5, 1, 5] as const;
export const TWAP_INDEX_PCTS = [0.1, 0.25, 0.5, 1] as const;
export const TWAP_MIN_FREQ = 2;
export const TWAP_MAX_FREQ = 3600;
export const TWAP_DEFAULT_FREQ = 5;
export type TwapStyle = "passive" | "neutral" | "aggressive";

export function twapDurationSeconds(hours: string, minutes: string): number | null {
  const h = parseDecimal(hours) ?? 0;
  const m = parseDecimal(minutes) ?? 0;
  if (h < 0 || m < 0) return null;
  if (h === 0 && m === 0) return null;
  const sec = Math.round(h * 3600 + m * 60);
  if (sec < TWAP_MIN_SECONDS || sec > TWAP_MAX_SECONDS) return null;
  return sec;
}

export function twapOrderCount(durationSec: number, sliceSec: number = TWAP_SLICE_SECONDS): number {
  if (!(durationSec > 0) || !(sliceSec > 0)) return 0;
  return Math.floor(durationSec / sliceSec) + 1;
}

export function twapFreqSeconds(raw: string): number | null {
  const n = parseDecimal(raw);
  if (n == null) return null;
  const sec = Math.round(n);
  if (sec < TWAP_MIN_FREQ || sec > TWAP_MAX_FREQ) return null;
  return sec;
}

export function twapFreqLabel(freqSec: number, randomize: boolean): string {
  return randomize ? `${freqSec}s (±40%)` : `${freqSec}s`;
}

export function formatTwapRuntime(sec: number): string {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const parts: string[] = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m || parts.length === 0) parts.push(`${m}m`);
  return parts.join(" ");
}

export function twapSlipFromMaxPrice(maxPrice: number, spot: number): number | null {
  if (!(spot > 0) || !(maxPrice > 0)) return null;
  return Math.abs(maxPrice - spot) / spot;
}

export function algoById(id: AlgoId): AlgoDef {
  return ALGOS.find((a) => a.id === id) ?? ALGOS[0];
}

const PAUSE_COPY: Record<string, string> = {
  below_floor: "Bid below floor",
  above_ceiling: "Ask above ceiling",
  would_cross: "Would cross",
  below_min_qty: "Below min size",
  no_book: "Waiting for book",
  no_market: "Unknown market",
  invalid_band: "Set floor / ceiling",
  invalid_offset: "Offset",
  invalid_nonce: "Nonce — retrying",
  rate_limited: "Rate limited — backing off",
  requote_wait: "Holding clip",
  book_unsynced: "Book syncing",
  account_unsynced: "Account feed syncing",
  shutdown: "Shutdown — waiting",
  unproven_missing_clip: "Clip vanished — resume to retry",
  trades_reconcile_failed: "Trade sync failed — resume to retry",
  user_paused: "Paused",
  child_still_open: "Child still on book",
  above_max_price: "Above max price",
  below_max_price: "Below max price",
  past_index: "Past index",
  no_mark: "Waiting for mark",
  deadline: "Duration ended",
};

export function algoReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "";
  return PAUSE_COPY[reason] ?? reason.replaceAll("_", " ");
}

export function algoIsWorking(status: string | null | undefined): boolean {
  return status === "running" || status === "paused" || status === "error";
}

export function algoIsPaused(status: string | null | undefined): boolean {
  return status === "paused";
}

export function algoPhase(algo: {
  status: string;
  quote_action?: string | null;
  rest_price?: string | null;
}): { key: string; label: string; tone: "bid" | "ask" | "muted" | "warn" } {
  if (algo.status === "error") return { key: "err", label: "Error", tone: "ask" };
  if (algo.status === "done") return { key: "done", label: "Filled", tone: "muted" };
  if (algo.status === "stopped") return { key: "stop", label: "Stopped", tone: "muted" };
  if (algo.status === "paused") return { key: "paused", label: "Paused", tone: "warn" };
  if (algo.quote_action === "rest" && algo.rest_price) {
    return { key: "active", label: "Active", tone: "bid" };
  }
  if (algo.quote_action === "pause") {
    return { key: "wait", label: "Waiting", tone: "warn" };
  }
  return { key: "run", label: "Working", tone: "muted" };
}

export function algoFillProgress(algo: {
  qty?: string | null;
  filled?: string | null;
  remaining?: string | null;
  fills?: { qty: string }[] | null;
  clips?: { filled?: string | null; qty?: string | null }[] | null;
}): { filled: number; remaining: number; total: number; pct: number } {
  const qty = parseFloat(algo.qty ?? "");
  const filledField = parseFloat(algo.filled ?? "");
  const remainingField = parseFloat(algo.remaining ?? "");
  const total = Number.isFinite(qty) && qty > 0 ? qty : 0;
  const hasFilled = Number.isFinite(filledField) && filledField >= 0;
  const hasRemaining = Number.isFinite(remainingField) && remainingField >= 0;

  const fromClips = (algo.clips ?? []).reduce((s, c) => {
    const f = parseFloat(c.filled ?? "");
    const q = parseFloat(c.qty ?? "");
    if (!Number.isFinite(f) || f <= 0) return s;
    if (Number.isFinite(q) && q > 0) return s + Math.min(f, q);
    return s + f;
  }, 0);
  const fromFills = (algo.fills ?? []).reduce((s, f) => s + (parseFloat(f.qty) || 0), 0);

  let filled: number;
  let remaining: number;

  // Prefer backend master fields, but never show less filled than the clips /
  // fill tape already prove (guards master/tape drift).
  if (total > 0 && hasRemaining) {
    remaining = Math.min(total, Math.max(0, remainingField));
    filled = Math.max(0, total - remaining);
  } else if (total > 0 && hasFilled) {
    filled = Math.min(total, Math.max(0, filledField));
    remaining = Math.max(0, total - filled);
  } else {
    filled = Math.max(0, fromClips, fromFills);
    if (total > 0) filled = Math.min(total, filled);
    remaining = total > 0 ? Math.max(0, total - filled) : 0;
  }

  const proven = fromClips;
  if (total > 0 && proven > filled) {
    filled = Math.min(total, proven);
    remaining = Math.max(0, total - filled);
  }

  const pct = total > 0 ? Math.min(100, (filled / total) * 100) : 0;
  return { filled, remaining, total, pct };
}

export function algoIsLive(status: string | null | undefined): boolean {
  return algoIsWorking(status);
}

/** Chase clips use [8e9, 9e9). Advanced TWAP uses [7e9, 8e9). */
export const CHASE_COI_BASE = 8_000_000_000;
export const CHASE_COI_END = 9_000_000_000;
export const TWAP_COI_BASE = 7_000_000_000;
export const TWAP_COI_END = 8_000_000_000;

export function isChaseClientOrder(coi: string | number | null | undefined): boolean {
  if (coi == null || coi === "") return false;
  const n = typeof coi === "number" ? coi : Number(coi);
  return Number.isFinite(n) && n >= CHASE_COI_BASE && n < CHASE_COI_END;
}

export function isTwapClientOrder(coi: string | number | null | undefined): boolean {
  if (coi == null || coi === "") return false;
  const n = typeof coi === "number" ? coi : Number(coi);
  return Number.isFinite(n) && n >= TWAP_COI_BASE && n < TWAP_COI_END;
}

export function isAlgoClientOrder(coi: string | number | null | undefined): boolean {
  return isChaseClientOrder(coi) || isTwapClientOrder(coi);
}

export function algoOrderKind(coi: string | number | null | undefined): "Chase" | "TWAP" | null {
  if (isChaseClientOrder(coi)) return "Chase";
  if (isTwapClientOrder(coi)) return "TWAP";
  return null;
}

export function isAlgoChildOrder(
  order: { client_order_index: string | number },
  algo?: {
    working_coi?: number | null;
    clips?: { client_order_index: number; status: string }[] | null;
  } | null
): boolean {
  if (isAlgoClientOrder(order.client_order_index)) return true;
  if (!algo) return false;
  const coi = Number(order.client_order_index);
  if (algo.working_coi != null && coi === algo.working_coi) return true;
  return (algo.clips ?? []).some(
    (c) => c.status === "live" && c.client_order_index === coi
  );
}

export function algoBlotter(book: import("./api").AlgoBook | import("./api").AlgoState | null): {
  working: import("./api").AlgoState[];
  history: import("./api").AlgoState[];
} {
  if (!book) return { working: [], history: [] };
  if (Array.isArray((book as import("./api").AlgoBook).working)) {
    const b = book as import("./api").AlgoBook;
    return { working: b.working ?? [], history: b.history ?? [] };
  }
  const algo = book as import("./api").AlgoState;
  const working = algoIsWorking(algo.status) && algo.algo_id ? [algo] : [];
  return { working, history: [] };
}

function isSpotMarket(m: Market): boolean {
  return m.is_perp === false || m.market_type === "spot" || m.market_type === "spot_market";
}

function marketSymbol(m: Market | null | undefined): string {
  return (m?.symbol ?? "").toUpperCase();
}

export function spotPerpPair(
  markets: Market[],
  symbol: string
): { perp: Market; spot: Market } | null {
  const want = (symbol ?? "").toUpperCase();
  if (!want) return null;
  const same = markets.filter((m) => marketSymbol(m) === want);
  const spot = same.find(isSpotMarket);
  const perp = same.find((m) => !isSpotMarket(m));
  if (!perp || !spot) return null;
  return { perp, spot };
}

export function preferPerpMarket(markets: Market[], symbol: string): Market | undefined {
  const pair = spotPerpPair(markets, symbol);
  if (pair) return pair.perp;
  const want = (symbol ?? "").toUpperCase();
  if (!want) return undefined;
  return markets.find((m) => marketSymbol(m) === want);
}

/** One row per symbol in pickers — perp wins when a spot twin exists. */
export function uniqueSymbolMarkets(markets: Market[]): Market[] {
  const bySym = new Map<string, Market>();
  for (const m of markets) {
    const key = marketSymbol(m);
    if (!key) continue;
    const prev = bySym.get(key);
    if (!prev || (isSpotMarket(prev) && !isSpotMarket(m))) {
      bySym.set(key, m);
    }
  }
  return [...bySym.values()];
}

export function sameMarketIndex(a: unknown, b: unknown): boolean {
  if (a == null || b == null || a === "" || b === "") return false;
  const na = Number(a);
  const nb = Number(b);
  return Number.isFinite(na) && Number.isFinite(nb) && na === nb;
}
