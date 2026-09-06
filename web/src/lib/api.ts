const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiDetail(err.detail, res.statusText));
  }
  return res.json();
}

function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "object" && item && "msg" in item) {
          return String((item as { msg: string }).msg);
        }
        return String(item);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "msg" in detail) {
    return String((detail as { msg: string }).msg);
  }
  return fallback;
}

export interface Market {
  market_index: number;
  symbol: string;
  price_decimals: number;
  size_decimals: number;
  min_base_amount?: number;
  min_quote_amount?: number;
  mark_price?: number | null;
  index_price?: number | null;
  last_trade_price?: number | null;
  max_leverage?: number;
  default_leverage?: number;
  allowed_leverages?: number[];
  volume_24h?: number;
  volume_base_24h?: number;
  change_24h?: number | null;
  funding_rate?: number | null;
  funding_apr?: number | null;
  open_interest?: number | null;
  open_interest_limit?: number | null;
  best_bid_price?: number | null;
  best_ask_price?: number | null;
  mid_price?: number | null;
  premium?: number | null;
  funding_timestamp?: number | null;
  daily_price_high?: number | null;
  daily_price_low?: number | null;
  market_type?: string | null;
  is_perp?: boolean;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Position {
  market_index: number;
  symbol: string;
  size: string;
  entry_price: string;
  mark_price: string;
  unrealized_pnl: string;
  leverage: number;
  margin_mode: string;
  liquidation_price?: string;
  funding_paid?: string;
  allocated_margin?: string;
  side?: "long" | "short";
}

export function isLongPosition(p: Pick<Position, "size" | "side">): boolean {
  if (p.side === "short") return false;
  if (p.side === "long") return true;
  return parseFloat(p.size) > 0;
}

export interface OpenOrder {
  /** Lighter order id — string because values exceed JS safe integers. */
  order_index: string;
  client_order_index: string;
  market_index: number;
  symbol: string;
  side: string;
  price: string;
  size: string;
  remaining: string;
  order_type: string;
  reduce_only: boolean;
}

export interface Account {
  collateral: string;
  available: string;
  /** USDC free + haircut multi-asset margin — use for max order size. */
  trade_available?: string;
  unrealized_pnl: string;
  positions: Position[];
  open_orders: OpenOrder[];
}

export interface AccountTrade {
  trade_id: string;
  market_index: number;
  symbol: string;
  side: "buy" | "sell";
  is_maker: boolean;
  price: string;
  size: string;
  usd_amount: string;
  fee: string;
  pnl: string;
  type: string;
  timestamp: number;
}

export interface AccountFunding {
  funding_id: number;
  market_index: number;
  symbol: string;
  side: "long" | "short";
  position_size: string;
  rate: string;
  change: string;
  discount: string;
  timestamp: number;
}

export interface AccountTradesPage {
  trades: AccountTrade[];
  next_cursor: string | null;
}

export interface AccountFundingPage {
  fundings: AccountFunding[];
  next_cursor: string | null;
}

export interface AlgoClip {
  seq: number;
  client_order_index: string | number;
  order_index: string | number | null;
  side?: string | null;
  price: string;
  qty: string;
  filled: string;
  remaining: string;
  status: "live" | "filled" | "cancelled";
  placed_at: number;
  closed_at: number | null;
}

export interface AlgoFill {
  seq: number;
  clip_seq: number;
  price: string;
  qty: string;
  ts: number;
  order_index: string | number | null;
  client_order_index: string | number | null;
}

export interface AlgoState {
  type: string;
  id: string;
  algo_type?: string;
  version?: string;
  algo_id?: string | null;
  status: string;
  market_index?: number;
  symbol?: string;
  side?: string | null;
  qty?: string | null;
  display_qty?: string | null;
  offset_bps?: string | null;
  price_floor?: string | null;
  price_ceiling?: string | null;
  remaining?: string | null;
  filled?: string | null;
  quote_action?: string | null;
  reason?: string | null;
  rest_price?: string | null;
  rest_qty?: string | null;
  params_json?: Record<string, unknown> | null;
  working_coi?: number | null;
  working_order_index?: string | number | null;
  error?: string | null;
  reduce_only?: boolean;
  created_at?: number | null;
  clips?: AlgoClip[];
  fills?: AlgoFill[];
  working?: AlgoClip | null;
}

export interface AlgoBook {
  type?: string;
  id?: string;
  working: AlgoState[];
  history: AlgoState[];
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

export type AlertKind =
  | "oi"
  | "volume"
  | "spread"
  | "price"
  | "premium"
  | "dislocation"
  | "funding"
  | "liq_cluster";

export interface AlertEvent {
  id: string;
  ts: number;
  symbol: string;
  market_index: number;
  kind: AlertKind;
  severity: number;
  direction: string;
  value: number;
  baseline: number | null;
  unit: string;
  note: string;
}

export const api = {
  health: () =>
    request<{
      status: string;
      network: string;
      trading_enabled: boolean;
      market_ws?: string;
      account_ws?: string;
    }>("/health"),
  markets: () => request<Market[]>("/markets"),
  market: (symbol: string) => request<Market>(`/markets/${symbol}`),
  candles: (symbol: string, resolution = "1m", count = 500) =>
    request<Candle[]>(`/candles/${symbol}?resolution=${resolution}&count=${count}`),
  activateMarket: (symbol: string) =>
    request<{ status: string }>(`/markets/${symbol}/activate`, { method: "POST" }),
  account: () => request<Account>("/account"),
  liquidations: (opts?: { limit?: number; min_usd?: number; market_index?: number }) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    if (opts?.min_usd != null) q.set("min_usd", String(opts.min_usd));
    if (opts?.market_index != null) q.set("market_index", String(opts.market_index));
    const qs = q.toString();
    return request<LiquidationEvent[]>(`/liquidations${qs ? `?${qs}` : ""}`);
  },
  alerts: (opts?: { limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<AlertEvent[]>(`/alerts${qs ? `?${qs}` : ""}`);
  },
  placeMarketOrder: (body: Record<string, unknown>) =>
    request("/orders/market", { method: "POST", body: JSON.stringify(body) }),
  placeLimitOrder: (body: Record<string, unknown>) =>
    request("/orders/limit", { method: "POST", body: JSON.stringify(body) }),
  placeTwapOrder: (body: Record<string, unknown>) =>
    request("/orders/twap", { method: "POST", body: JSON.stringify(body) }),
  cancelOrder: (market_index: number, order_index: string | number) =>
    request("/orders/cancel", {
      method: "POST",
      body: JSON.stringify({ market_index, order_index: String(order_index) }),
    }),
  cancelAll: (market_index?: number | null) =>
    request("/orders/cancel-all", {
      method: "POST",
      body: JSON.stringify({ market_index: market_index ?? null }),
    }),
  updateLeverage: (market_index: number, leverage: number, cross: boolean) =>
    request("/leverage", {
      method: "POST",
      body: JSON.stringify({ market_index, leverage, cross }),
    }),
  accountTrades: (opts?: { market_index?: number | null; cursor?: string | null; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.market_index != null) q.set("market_index", String(opts.market_index));
    if (opts?.cursor) q.set("cursor", opts.cursor);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<AccountTradesPage>(`/account/trades${qs ? `?${qs}` : ""}`);
  },
  accountFunding: (opts?: { market_index?: number | null; cursor?: string | null; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.market_index != null) q.set("market_index", String(opts.market_index));
    if (opts?.cursor) q.set("cursor", opts.cursor);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<AccountFundingPage>(`/account/funding${qs ? `?${qs}` : ""}`);
  },
  chaseStatus: () => request<AlgoBook>("/algos/chase-iceberg"),
  algoStatus: () => request<AlgoBook>("/algos"),
  chaseStart: (body: Record<string, unknown>) =>
    request<AlgoBook>("/algos/chase-iceberg/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chaseStop: (algo_id?: string | null) =>
    request<AlgoBook>("/algos/chase-iceberg/stop", {
      method: "POST",
      body: JSON.stringify({ algo_id: algo_id ?? null }),
    }),
  chasePause: (algo_id: string) =>
    request<AlgoBook>("/algos/chase-iceberg/pause", {
      method: "POST",
      body: JSON.stringify({ algo_id }),
    }),
  chaseUnpause: (algo_id: string) =>
    request<AlgoBook>("/algos/chase-iceberg/unpause", {
      method: "POST",
      body: JSON.stringify({ algo_id }),
    }),
  kill: (flatten = false) =>
    request<{
      status: string;
      cancel_ok?: boolean;
      cancel_error?: string | null;
      flatten?: Array<{ market_index?: number; symbol?: string; ok?: boolean; error?: string | null }>;
      algos?: AlgoBook;
    }>("/kill", { method: "POST", body: JSON.stringify({ flatten }) }),
};
