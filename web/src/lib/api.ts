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

export interface OpenInterestSample {
  time: number;
  open_interest: number;
}

/** One funding bucket. `rate` is the 1h rate in percent; unsettled buckets are the estimate. */
export interface FundingSample {
  time: number;
  rate: number;
  settled: boolean;
}

/**
 * Mean settled 1h rate (percent) per window; `hours` is how many settled hours it holds.
 * `venue_days` of those are whole days taken from Lighter's daily history, 24 hours each.
 */
export interface FundingAverage {
  windows: {
    label: string;
    days: number;
    hours: number;
    venue_days?: number;
    rate: number | null;
  }[];
  first_time: number | null;
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

export interface Asset {
  symbol: string;
  balance: string;
  margin_balance: string;
  available: string;
  index_price: string;
  ltv: string;
  usd: string;
  unrealized_pnl: string;
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
  trigger_price?: string;
}

export interface Account {
  collateral: string;
  available: string;
  /** Free margin for max order size: USDC available + LTV of non-quote collateral. */
  trade_available?: string;
  portfolio_margin?: string;
  unrealized_pnl: string;
  user_tier?: string | null;
  maker_fee_bps?: string;
  taker_fee_bps?: string;
  positions: Position[];
  open_orders: OpenOrder[];
  assets?: Asset[];
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

export interface JournalFill {
  trade_id: string;
  ts: number;
  side: string;
  price: string;
  size: string;
  fee: string;
  pnl: string;
  is_maker: boolean;
  closing: boolean;
}

export interface JournalTrip {
  trip_key: string;
  market_index: number;
  symbol: string;
  side: string;
  open_ts: number;
  close_ts: number | null;
  size: string | null;
  avg_in: string | null;
  avg_out: string | null;
  net: string | null;
  fees: string | null;
  funding: string | null;
  algo: string;
  r: string | null;
  partial: boolean;
  partial_reason: string | null;
  open: boolean;
  upnl: string | null;
  note: string;
  tags: string[];
  fills: JournalFill[];
}

export interface JournalSummaryGroup {
  key: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: string | null;
  net: string | null;
  fees: string | null;
  funding: string | null;
  profit_factor: string | null;
  expectancy: string | null;
  avg_r: string | null;
  max_drawdown: string | null;
  curve: { ts: number; net: string | null }[];
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
  kind?: string | null;
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
  working_bid?: AlgoClip | null;
  working_ask?: AlgoClip | null;
  inventory?: string | null;
  inventory_vwap?: string | null;
  captured_pnl?: string | null;
  profit_bps?: string | null;
  grid_bps?: string | null;
  be_delay_ms?: number | null;
  merged_active?: boolean;
  lots?: {
    lot_id: string;
    cell_price: string;
    qty: string;
    vwap: string;
    side: string;
    tp_price: string;
    merged?: boolean;
  }[];
  planner?: PlannerRuntime | null;
  trail?: TrailRuntime | null;
}

export type TrailKind = "entry" | "stop" | "tp";
export type TrailReference = "mark" | "last";
export type TrailDistanceKind = "pct" | "price";

/** A Trail as the desk runs it (docs/trail-rules.md). */
export interface TrailRuntime {
  kind: TrailKind;
  /** The side of the order it fires: the closing side for a Stop or Take Profit. */
  side: "buy" | "sell";
  qty: string;
  reference: TrailReference;
  distance: string;
  distance_kind: TrailDistanceKind;
  activation: string | null;
  /** A Stop's start price; the trigger is never worse. */
  floor: string | null;
  active: boolean;
  best: string | null;
  trigger: string | null;
  /** Where its venue Stop sits now. */
  venue_trigger: string | null;
  last_move_ms: number | null;
  fired_at: number | null;
  fired_price: string | null;
  deadline_ms: number | null;
  /** False while the market feed is not live (F10). */
  following: boolean;
  /** On Last, the venue Stop is a backstop one step behind (L2). */
  backstop: boolean;
  clip_roles?: Record<string, string>;
}

export interface TrailPreview {
  resolved: {
    side: "buy" | "sell";
    qty: string;
    start: string | null;
    activation: string | null;
    mark: string | null;
    step: string | null;
    trigger_now: string | null;
  } | null;
  refused: PlannerRefusal | null;
  replaces: OpenOrder[];
}

export interface PlannerTargetPlan {
  index: number;
  price: string;
  qty: string;
  pct: string;
  r: string;
  move_pct: string;
  order?: "limit" | "trigger" | "trail";
  /** A Trail target's distance: a price, or a % of the best price. */
  trail_distance?: string | null;
  trail_kind?: "price" | "pct";
}

/** What Planner will send: every number comes from one stop (docs/planner-rules.md). */
export interface PlannerPlan {
  side: "buy" | "sell";
  entry: string;
  stop: string;
  r: string;
  size: string;
  targets: PlannerTargetPlan[];
  runner: string;
  risk_usd: string;
  risk_pct: string | null;
  breakeven: string;
  stop_pct: string;
  warnings: string[];
  /** Stop steps: once target `after` fills, the stop moves to `price`. */
  steps: PlannerStep[];
  /** EL1: a Ladder entry's rungs, nearest the market first. Empty once the entry ends. */
  rungs?: PlannerRung[];
}

export interface PlannerRung {
  index: number;
  price: string;
  qty: string;
}

export interface PlannerStep {
  after: number;
  price: string;
  /** "breakeven" or "tp1", "tp2"… */
  to: string;
}

export interface PlannerRefusal {
  rule: string;
  message: string;
}

export interface PlannerPreview {
  plan: PlannerPlan | null;
  refused: PlannerRefusal | null;
  replaces: OpenOrder[];
  equity: string | null;
  mark: string;
}

export interface PlannerRuntime {
  phase: "entering" | "managing";
  plan: PlannerPlan | null;
  roles: Record<string, string>;
  entry_filled: string;
  expected_size: string;
  stop_trigger: string | null;
  breakeven_done: boolean;
  /** The target number of the last Stop step taken; 0 before any. */
  steps_done?: number;
  entry_deadline_ms: number | null;
  /** Where each trailing part is: "entry", "stop", "tp2"… */
  trails?: Record<string, { active: boolean; best: string | null; trigger: string | null }>;
  /** client_order_index → "entry" | "stop" | "tp1"… */
  clip_roles?: Record<string, string>;
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
  fill_count?: number;
  timestamp: number;
}

export type LiquidationSummaryHours = 1 | 4 | 24 | 168 | 720;

export interface LiquidationSummaryRow {
  symbol: string;
  market_index: number;
  long_usd: number;
  short_usd: number;
  total_usd: number;
  fill_count: number;
  largest_usd: number;
}

export interface LiquidationSummary {
  hours: number;
  since: number;
  rows: LiquidationSummaryRow[];
}

export type AlertRule = "move" | "volume" | "oi" | "liqs" | "board" | "near_liq";

/** One thing an alert row states. A rule that fired has a size; what the tape showed has none. */
export interface AlertFact {
  kind: string;
  direction?: string;
  value: number;
  unit: string;
  window?: string;
  /** Times its threshold. */
  size?: number;
  /** A spike's minute, as a multiple of the hour's biggest minute. */
  multiple?: number;
  /** Move: share of the Day range, 0 to 1. */
  share?: number;
  /** Move: the part beyond the Broad move. */
  excess?: number;
  /** Open interest: the change in USD. */
  usd?: number;
  /** Funding: sigmas from its own 24h median. */
  z?: number;
  /** Liquidations: basis points of open interest. */
  bps?: number;
  /** Board: liquid perps counted. */
  liquid?: number;
  liquidation_price?: number;
}

export interface AlertRuleStats {
  rule: string;
  n: number;
  measured: number;
  /** Median Left, percent. Null until a row has its bars. */
  left: number | null;
  against: number | null;
  opened: number;
}

export interface AlertStats {
  hours: number;
  rules: AlertRuleStats[];
}

/** One liquid perp on the Activity board. A null cell has no baseline yet. */
export interface ScanActivityRow {
  market_index: number;
  symbol: string;
  move_5m: number | null;
  /** The 5m move as a share of the Day range, 0 to 1. */
  share: number | null;
  day_range: number;
  vol_x: number | null;
  vol_usd_5m: number | null;
  oi_5m: number | null;
  oi_usd_5m: number | null;
  funding: number;
  funding_z: number | null;
  premium: number;
  premium_z: number | null;
  held: boolean;
}

/** A market on the funding strip: its hourly rate is far from its own day. */
export interface FundingExtremeRow {
  market_index: number;
  symbol: string;
  funding: number;
  z: number;
  held: boolean;
}

export interface ToneBoardRow {
  market_index: number;
  symbol: string;
  timeframe: string;
  tone: "blue" | "orange";
  closed_at: number;
  close: number;
}

export interface ToneTimeframes {
  timeframes: string[];
  choices: string[];
  cap: number;
}

export interface AutoKillState {
  type?: string;
  armed: boolean;
  loss_usd: number | null;
  profit_usd: number | null;
  fired_at: number | null;
  fired_reason: string | null;
  fired_upnl: number | null;
  last_kill_status: string | null;
}

export interface AlertEvent {
  id: string;
  ts: number;
  symbol: string;
  market_index: number;
  /** The largest rule on the row. */
  rule: AlertRule;
  severity: number;
  direction: string;
  size: number;
  price: number;
  facts: AlertFact[];
  /** "long", "short", "order" for a working order with no Position, or "". */
  held: string;
  started_at: number;
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
  openInterest: (symbol: string, resolution = "1m", count = 500) =>
    request<OpenInterestSample[]>(`/oi/${symbol}?resolution=${resolution}&count=${count}`),
  funding: (symbol: string, resolution = "1h", count = 500) =>
    request<FundingSample[]>(`/funding/${symbol}?resolution=${resolution}&count=${count}`),
  fundingAverage: (symbol: string) => request<FundingAverage>(`/funding/${symbol}/average`),
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
  liquidationSummary: (hours: LiquidationSummaryHours) =>
    request<LiquidationSummary>(`/liquidations/summary?hours=${hours}`),
  alerts: (opts?: { limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<AlertEvent[]>(`/alerts${qs ? `?${qs}` : ""}`);
  },
  alertStats: (hours = 24) => request<AlertStats>(`/alerts/stats?hours=${hours}`),
  fundingExtremes: () => request<FundingExtremeRow[]>("/alerts/funding"),
  alertOpened: (id: string) =>
    request<{ status: string }>(`/alerts/${encodeURIComponent(id)}/opened`, { method: "POST" }),
  pushStatus: () =>
    request<{ enabled: boolean; chat_set: boolean; alerts: string; algos: string }>("/push"),
  pushTest: () => request<{ ok: boolean; error?: string }>("/push/test", { method: "POST" }),
  scanActivity: () => request<ScanActivityRow[]>("/scan/activity"),
  toneBoard: () => request<ToneBoardRow[]>("/scan/tones"),
  toneTimeframes: () => request<ToneTimeframes>("/scan/tones/timeframes"),
  setToneTimeframes: (timeframes: string[]) =>
    request<ToneTimeframes>("/scan/tones/timeframes", {
      method: "PUT",
      body: JSON.stringify({ timeframes }),
    }),
  placeMarketOrder: (body: Record<string, unknown>) =>
    request("/orders/market", { method: "POST", body: JSON.stringify(body) }),
  placeLimitOrder: (body: Record<string, unknown>) =>
    request("/orders/limit", { method: "POST", body: JSON.stringify(body) }),
  placeTwapOrder: (body: Record<string, unknown>) =>
    request("/orders/twap", { method: "POST", body: JSON.stringify(body) }),
  placeStopTake: (body: Record<string, unknown>) =>
    request("/orders/sl-tp", { method: "POST", body: JSON.stringify(body) }),
  cancelOrder: (market_index: number, order_index: string | number) =>
    request("/orders/cancel", {
      method: "POST",
      body: JSON.stringify({ market_index, order_index: String(order_index) }),
    }),
  amendOrder: (
    market_index: number,
    order_index: string | number,
    price: string,
    size?: string,
  ) =>
    request("/orders/modify", {
      method: "POST",
      body: JSON.stringify({
        market_index,
        order_index: String(order_index),
        price,
        ...(size != null ? { size } : {}),
      }),
    }),
  cancelAll: (market_index?: number | null) =>
    request("/orders/cancel-all", {
      method: "POST",
      body: JSON.stringify({ market_index: market_index ?? null }),
    }),
  cancelTickets: (side: "buy" | "sell", market_index?: number | null) =>
    request<{ cancelled: number; error?: string }>("/orders/cancel-side", {
      method: "POST",
      body: JSON.stringify({ side, market_index: market_index ?? null }),
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
  journalTrips: (opts?: { since?: number; until?: number; market?: string; algo?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.since != null) q.set("since", String(opts.since));
    if (opts?.until != null) q.set("until", String(opts.until));
    if (opts?.market) q.set("market", opts.market);
    if (opts?.algo) q.set("algo", opts.algo);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<{ trips: JournalTrip[] }>(`/journal/trips${qs ? `?${qs}` : ""}`);
  },
  journalSummary: (opts: { range: string; group: string; market?: string; algo?: string }) => {
    const q = new URLSearchParams({ range: opts.range, group: opts.group });
    if (opts.market) q.set("market", opts.market);
    if (opts.algo) q.set("algo", opts.algo);
    return request<{ range: string; group: string; groups: JournalSummaryGroup[] }>(
      `/journal/summary?${q.toString()}`,
    );
  },
  journalNote: (tripKey: string, body: { note: string; tags: string[] }) =>
    request<{ trip_key: string; note: string; tags: string[] }>(
      `/journal/trips/${encodeURIComponent(tripKey)}/note`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  journalSync: () =>
    request<{ started: boolean; last_synced_at: number | null }>("/journal/sync", { method: "POST" }),
  accountFunding: (opts?: { market_index?: number | null; cursor?: string | null; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.market_index != null) q.set("market_index", String(opts.market_index));
    if (opts?.cursor) q.set("cursor", opts.cursor);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<AccountFundingPage>(`/account/funding${qs ? `?${qs}` : ""}`);
  },
  algoStatus: () => request<AlgoBook>("/algos"),
  algoStart: (algoType: string, body: Record<string, unknown>) =>
    request<AlgoBook>(`/algos/${encodeURIComponent(algoType)}/start`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  algoStop: (algo_id?: string | null) =>
    request<AlgoBook>("/algos/stop", {
      method: "POST",
      body: JSON.stringify({ algo_id: algo_id ?? null }),
    }),
  algoPause: (algo_id: string) =>
    request<AlgoBook>("/algos/pause", {
      method: "POST",
      body: JSON.stringify({ algo_id }),
    }),
  algoUnpause: (algo_id: string) =>
    request<AlgoBook>("/algos/unpause", {
      method: "POST",
      body: JSON.stringify({ algo_id }),
    }),
  plannerPreview: (body: Record<string, unknown>) =>
    request<PlannerPreview>("/algos/planner/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  plannerFinishEntry: (algo_id: string) =>
    request<AlgoBook>("/algos/planner/finish-entry", {
      method: "POST",
      body: JSON.stringify({ algo_id }),
    }),
  plannerReplan: (body: Record<string, unknown>) =>
    request<AlgoBook>("/algos/planner/replan", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  trailPreview: (body: Record<string, unknown>) =>
    request<TrailPreview>("/algos/trail/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  trailEdit: (body: Record<string, unknown>) =>
    request<AlgoBook>("/algos/trail/edit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  trailStop: (algo_id: string, keepStop: boolean) =>
    request<AlgoBook>("/algos/trail/stop", {
      method: "POST",
      body: JSON.stringify({ algo_id, keep_stop: keepStop }),
    }),
  kill: (flatten = false) =>
    request<{
      status: string;
      cancel_ok?: boolean;
      cancel_error?: string | null;
      algo_error?: string | null;
      flatten?: Array<{ market_index?: number; symbol?: string; ok?: boolean; error?: string | null }>;
      algos?: AlgoBook;
    }>("/kill", { method: "POST", body: JSON.stringify({ flatten }) }),
  autoKill: () => request<AutoKillState>("/kill/auto"),
  setAutoKill: (body: { armed: boolean; loss_usd?: number | null; profit_usd?: number | null }) =>
    request<AutoKillState>("/kill/auto", { method: "PUT", body: JSON.stringify(body) }),
};
