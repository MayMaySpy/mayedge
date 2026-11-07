import type {
  AutoKillRequest,
  IdeaAlertBody,
  IdeaAlertSaved,
  IdeaAlerts,
  IdeaBody,
  IdeaCreated,
  IdeaDetail,
  IdeaLogBody,
  IdeaLogged,
  IdeaPatch,
  IdeaPlannerBody,
  IdeaReviewBody,
  IdeaSaved,
  IdeaStatusBody,
  Ideas,
  JournalExcursion,
  JournalNote,
  JournalSummary,
  JournalSync,
  JournalTrips,
  LimitOrderRequest,
  MarketOrderRequest,
  PortfolioDays,
  PortfolioHistory,
  PortfolioNow,
  StopTakeRequest,
  TwapOrderRequest,
} from "@/lib/api.gen";

export type {
  Idea,
  IdeaBody,
  IdeaCreated,
  IdeaDetail,
  IdeaLogLine,
  IdeaPatch,
  IdeaReviewBody,
  IdeaSaved,
  IdeaStatusBody,
  Ideas,
  PortfolioMargin,
  JournalExcursion,
  JournalFill,
  JournalSide,
  JournalSummaryGroup,
  JournalTrip,
  LimitOrderRequest,
  MarketOrderRequest,
  PortfolioDay,
  PortfolioHistory,
  PortfolioKindNow,
  PortfolioNow,
  StopTakeRequest,
  TwapOrderRequest,
} from "@/lib/api.gen";

const API_BASE = "/api";

/** A refused desk call. `field` is set when the server names the input that broke. */
export class ApiError extends Error {
  readonly status: number;
  readonly field: string | null;

  constructor(status: number, message: string, field: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.field = field;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) throw await apiError(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function apiError(res: Response): Promise<ApiError> {
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  const parsed = readDetail(err.detail);
  return new ApiError(res.status, parsed.message || formatApiDetail(err.detail, res.statusText), parsed.field);
}

function readDetail(detail: unknown): { message: string | null; field: string | null } {
  if (typeof detail === "string") return { message: detail, field: null };
  if (Array.isArray(detail)) return { message: formatApiDetail(detail, ""), field: null };
  if (detail && typeof detail === "object") {
    const row = detail as { message?: unknown; msg?: unknown; field?: unknown };
    const message =
      typeof row.message === "string" ? row.message : typeof row.msg === "string" ? row.msg : null;
    const field = typeof row.field === "string" ? row.field : null;
    return { message, field };
  }
  return { message: null, field: null };
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
  const parsed = readDetail(detail);
  return parsed.message ?? fallback;
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

export type PortfolioKind = "perps" | "spot" | "llp" | "staking";

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
  /** Massager: its Core, Lean, Position, level, Core entry and Basis (massager-rules). */
  core?: string | null;
  lean?: string | null;
  position?: string | null;
  level?: number | null;
  catching?: boolean | null;
  core_entry?: string | null;
  basis?: string | null;
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
  /** What closing qty at price makes from entry, less the taker fee there (P10). */
  usd?: string;
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

export type LiquidationSummaryHours = 1 | 4 | 24 | 168 | 720 | 2160 | 8760;

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
  /** Preset length in hours. Null when the window is a from–to span. */
  hours: number | null;
  since: number;
  /** Exclusive end, ms. Null when the window runs up to now. */
  until: number | null;
  rows: LiquidationSummaryRow[];
}

export type AlertRule =
  | "move"
  | "volume"
  | "oi"
  | "liqs"
  | "board"
  | "near_liq"
  | "week_high"
  | "week_low"
  | "quarter_high"
  | "quarter_low";

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
  /** Week or quarter level: percent from that high or low. */
  distance?: number;
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
  left_p25?: number | null;
  left_p75?: number | null;
  against_p25?: number | null;
  against_p75?: number | null;
  /** Share of measured rows where Left beat Against. */
  left_beats?: number | null;
  opened: number;
  opened_rate?: number | null;
  key?: string;
}

export interface AlertStats {
  hours: number;
  by?: string;
  rules: AlertRuleStats[];
}

export interface AlertWhatIf {
  rule: string;
  knob: string;
  value: number;
  days: number;
  current: number;
  looser: boolean;
  baseline: AlertRuleStats;
  whatif: AlertRuleStats;
  yaml: string;
}

export interface AlertKnobSettings {
  knobs: Record<string, number>;
  by_rule: Record<string, string[]>;
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

/** docs/setup-rules.md: one row of the Setups board. */
export type SetupKind = "oi_price" | "funding" | "board" | "coil" | "reclaim" | "flush";

export interface SetupRow {
  kind: SetupKind;
  market_index: number;
  symbol: string;
  direction: "up" | "down" | "flat";
  size: number;
  price: number;
  note: string;
}

export interface SetupBoard {
  /** When the board was last rebuilt, ms. Null until the first build. */
  built_at: number | null;
  rows: SetupRow[];
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
  liquidations: (opts?: {
    limit?: number;
    min_usd?: number;
    market_index?: number;
    /** Next page: fills strictly older than this timestamp, ms. */
    before?: number;
    since?: number;
    until?: number;
  }) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    if (opts?.min_usd != null) q.set("min_usd", String(opts.min_usd));
    if (opts?.market_index != null) q.set("market_index", String(opts.market_index));
    if (opts?.before != null) q.set("before", String(opts.before));
    if (opts?.since != null) q.set("since", String(opts.since));
    if (opts?.until != null) q.set("until", String(opts.until));
    const qs = q.toString();
    return request<LiquidationEvent[]>(`/liquidations${qs ? `?${qs}` : ""}`);
  },
  liquidationSummary: (
    opts: { hours: LiquidationSummaryHours } | { since: number; until: number }
  ) => {
    const q = new URLSearchParams();
    if ("hours" in opts) q.set("hours", String(opts.hours));
    else {
      q.set("since", String(opts.since));
      q.set("until", String(opts.until));
    }
    return request<LiquidationSummary>(`/liquidations/summary?${q}`);
  },
  alerts: (opts?: { limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<AlertEvent[]>(`/alerts${qs ? `?${qs}` : ""}`);
  },
  alertStats: (hours = 24, by = "rule") =>
    request<AlertStats>(`/alerts/stats?hours=${hours}&by=${encodeURIComponent(by)}`),
  alertSettings: () => request<AlertKnobSettings>("/alerts/settings"),
  alertWhatIf: (opts: { rule: string; knob: string; value: number; days: number }) => {
    const q = new URLSearchParams({
      rule: opts.rule,
      knob: opts.knob,
      value: String(opts.value),
      days: String(opts.days),
    });
    return request<AlertWhatIf>(`/alerts/whatif?${q.toString()}`);
  },
  fundingExtremes: () => request<FundingExtremeRow[]>("/alerts/funding"),
  alertOpened: (id: string) =>
    request<{ status: string }>(`/alerts/${encodeURIComponent(id)}/opened`, { method: "POST" }),
  pushStatus: () =>
    request<{ enabled: boolean; chat_set: boolean; alerts: string; algos: string }>("/push"),
  pushTest: () => request<{ ok: boolean; error?: string }>("/push/test", { method: "POST" }),
  scanActivity: () => request<ScanActivityRow[]>("/scan/activity"),
  toneBoard: () => request<ToneBoardRow[]>("/scan/tones"),
  setups: () => request<SetupBoard>("/scan/setups"),
  toneTimeframes: () => request<ToneTimeframes>("/scan/tones/timeframes"),
  setToneTimeframes: (timeframes: string[]) =>
    request<ToneTimeframes>("/scan/tones/timeframes", {
      method: "PUT",
      body: JSON.stringify({ timeframes }),
    }),
  placeMarketOrder: (body: MarketOrderRequest) =>
    request("/orders/market", { method: "POST", body: JSON.stringify(body) }),
  placeLimitOrder: (body: LimitOrderRequest) =>
    request("/orders/limit", { method: "POST", body: JSON.stringify(body) }),
  placeTwapOrder: (body: TwapOrderRequest) =>
    request("/orders/twap", { method: "POST", body: JSON.stringify(body) }),
  placeStopTake: (body: StopTakeRequest) =>
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
    return request<JournalTrips>(`/journal/trips${qs ? `?${qs}` : ""}`);
  },
  journalSummary: (opts: { range: string; group: string; market?: string; algo?: string }) => {
    const q = new URLSearchParams({ range: opts.range, group: opts.group });
    if (opts.market) q.set("market", opts.market);
    if (opts.algo) q.set("algo", opts.algo);
    return request<JournalSummary>(
      `/journal/summary?${q.toString()}`,
    );
  },
  journalExcursion: (tripKey: string) =>
    request<JournalExcursion>(`/journal/trips/${encodeURIComponent(tripKey)}/excursion`),
  journalNote: (tripKey: string, body: { note: string; tags: string[] }) =>
    request<JournalNote>(
      `/journal/trips/${encodeURIComponent(tripKey)}/note`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  portfolio: (open: number, detail = true) =>
    request<PortfolioNow>(`/portfolio?open=${open}${detail ? "" : "&detail=false"}`),
  portfolioHistory: (range: string) =>
    request<PortfolioHistory>(`/portfolio/history?range=${encodeURIComponent(range)}`),
  portfolioDays: (range: string) =>
    request<PortfolioDays>(`/portfolio/days?range=${encodeURIComponent(range)}`),
  journalSync: () =>
    request<JournalSync>("/journal/sync", { method: "POST" }),
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
  setAutoKill: (body: AutoKillRequest) =>
    request<AutoKillState>("/kill/auto", { method: "PUT", body: JSON.stringify(body) }),
  ideas: (status = "all") => request<Ideas>(`/ideas?status=${encodeURIComponent(status)}`),
  idea: (id: string) => request<IdeaDetail>(`/ideas/${encodeURIComponent(id)}`),
  ideaCreate: (body: IdeaBody) =>
    request<IdeaCreated>("/ideas", { method: "POST", body: JSON.stringify(body) }),
  ideaPatch: (id: string, body: IdeaPatch) =>
    request<IdeaSaved>(`/ideas/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  ideaStatus: (id: string, body: IdeaStatusBody) =>
    request<IdeaSaved>(`/ideas/${encodeURIComponent(id)}/status`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ideaReview: (id: string, body: IdeaReviewBody) =>
    request<IdeaSaved>(`/ideas/${encodeURIComponent(id)}/review`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  ideaLog: (id: string, body: IdeaLogBody) =>
    request<IdeaLogged>(`/ideas/${encodeURIComponent(id)}/log`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ideaPlanner: (id: string, body: IdeaPlannerBody) =>
    request<IdeaSaved>(`/ideas/${encodeURIComponent(id)}/planner`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ideaDelete: (id: string) => request<void>(`/ideas/${encodeURIComponent(id)}`, { method: "DELETE" }),
  ideaAlerts: (id: string) => request<IdeaAlerts>(`/ideas/${encodeURIComponent(id)}/alerts`),
  ideaAlertCreate: (id: string, body: IdeaAlertBody) =>
    request<IdeaAlertSaved>(`/ideas/${encodeURIComponent(id)}/alerts`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ideaAlertsFromPlan: (id: string) =>
    request<IdeaAlerts>(`/ideas/${encodeURIComponent(id)}/alerts/plan`, { method: "POST" }),
  ideaAlertRearm: (alertId: number) =>
    request<IdeaAlertSaved>(`/idea-alerts/${alertId}/rearm`, { method: "POST" }),
  ideaAlertDelete: (alertId: number) => request<void>(`/idea-alerts/${alertId}`, { method: "DELETE" }),
};
