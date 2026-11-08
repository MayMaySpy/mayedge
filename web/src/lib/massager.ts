/**
 * The Massager's ticket preview. It mirrors the backend planner
 * (backend/src/mayedge/algos/massager/plan.py, docs/massager-rules.md MS1–MS8)
 * so the ticket can say what Start would do. The backend still decides.
 */

import { atr } from "@/lib/mayRekt";
import { parseDecimal } from "@/lib/numbers";

/** The ticket's own fields. Size is the Swing. */
export type MassagerStepMode = "fixed" | "atr";
export type MassagerAtrTf = "15m" | "1h" | "4h";

export interface MassagerParamsState {
  /** MS3: a Fixed Step is typed; an ATR Step is atrMult × ATR(14) on atrTf. */
  stepMode: MassagerStepMode;
  step: string;
  atrMult: string;
  atrTf: MassagerAtrTf;
  /** atrMult × the ATR now, kept by the sheet so Start can be checked. Empty until loaded. */
  atrStep: string;
  chaseFloor: string;
  chaseCeiling: string;
  /** MS22: begin a new Tally instead of carrying the last run's. */
  fresh: boolean;
  /** MS24: the Chop reading the sheet last made, sent with Start. Null until loaded. */
  chop: MassagerChop | null;
}

/** MS24: how much the last day of 1h candles ranged, and the Band it suggests. */
export type MassagerChopLabel = "ranging" | "mixed" | "trending";
export interface MassagerChop {
  er: number;
  label: MassagerChopLabel;
  /** Null when the mid is outside the day's range. */
  bandLow: number | null;
  bandHigh: number | null;
}

export const MASSAGER_CHOP_CANDLES = 24;
const CHOP_RANGING = 0.3;
const CHOP_MIXED = 0.5;
const HOUR_SEC = 3600;

export function chopLabelText(label: MassagerChopLabel): string {
  return label === "ranging" ? "Ranging" : label === "mixed" ? "Mixed" : "Trending";
}

/**
 * MS24: the efficiency ratio of the last 24 closed 1h candles, |last − first close| ÷ the sum
 * of each close's move, and a Band from their lowest low to highest high, rounded out to the
 * tick. Null without 24 closed candles or with no movement at all.
 */
export function chopReading(
  candles: readonly { time: number; high: number; low: number; close: number }[],
  { nowMs, mid, tick }: { nowMs: number; mid: number | null; tick: number }
): MassagerChop | null {
  const closed = candles
    .filter((c) => (c.time + HOUR_SEC) * 1000 <= nowMs)
    .slice(-MASSAGER_CHOP_CANDLES);
  if (closed.length < MASSAGER_CHOP_CANDLES) return null;
  let path = 0;
  for (let i = 1; i < closed.length; i++) path += Math.abs(closed[i].close - closed[i - 1].close);
  if (!(path > 0)) return null;
  const er = Math.abs(closed[closed.length - 1].close - closed[0].close) / path;
  const label: MassagerChopLabel =
    er < CHOP_RANGING ? "ranging" : er < CHOP_MIXED ? "mixed" : "trending";
  const lowest = Math.min(...closed.map((c) => c.low));
  const highest = Math.max(...closed.map((c) => c.high));
  const low = tick > 0 ? Math.floor(lowest / tick + EPS) * tick : lowest;
  const high = tick > 0 ? Math.ceil(highest / tick - EPS) * tick : highest;
  const inside = mid != null && mid >= low - EPS && mid <= high + EPS;
  return { er, label, bandLow: inside ? low : null, bandHigh: inside ? high : null };
}

/** MS24: the reading as Start sends it. */
export function chopBody(chop: MassagerChop, priceDecimals: number): Record<string, unknown> {
  return {
    label: chop.label,
    er: chop.er.toFixed(3),
    ...(chop.bandLow != null && chop.bandHigh != null
      ? { band_low: chop.bandLow.toFixed(priceDecimals), band_high: chop.bandHigh.toFixed(priceDecimals) }
      : {}),
    tf: "1h",
    n: MASSAGER_CHOP_CANDLES,
  };
}

/** MS19, MS22: what the desk says a Start would carry. */
export interface MassagerCarry {
  carried: boolean;
  why: string;
  source: string | null;
  basis?: string | null;
  entry?: string | null;
  captured?: string | null;
  runs?: number | null;
}

/** The Step the ticket would start with. */
export function massagerStepRaw(state: MassagerParamsState): string {
  return state.stepMode === "atr" ? state.atrStep : state.step;
}

export interface MassagerInput {
  bandLow: number;
  bandHigh: number;
  /** The ticket's size: the Swing asked for. */
  swing: number;
  step: number;
  /** Signed: long above zero. */
  position: number;
  mid: number | null;
  tick: number;
  sizeStep: number;
  minQty: number;
  makerBps: number;
}

export interface MassagerPreview {
  levels: number;
  /** Swing ÷ levels, down to the size step. */
  clip: number;
  /** levels × Clip: the run's Swing, at most the one asked for. */
  swing: number;
  center: number;
  step: number;
  /** Level k is prices[k + levels]. */
  prices: number[];
  /** Signed Position at the Band's top and bottom: Core − Swing and Core + Swing. */
  positionLow: number;
  positionHigh: number;
  /** One Clip sold and bought back a Step lower, before fees. */
  perRoundTrip: number;
  catchUp: { side: "buy" | "sell" | null; qty: number; level: number };
}

const EPS = 1e-9;

function roundToTick(price: number, tick: number): number {
  if (!(tick > 0)) return price;
  return Math.round(price / tick + EPS) * tick;
}

function floorTo(x: number, step: number): number {
  if (!(step > 0)) return x;
  return Math.floor(x / step + EPS) * step;
}

/** MS3: levels each side and the Clip the Step comes out at. */
function derive(input: MassagerInput): { levels: number; clip: number } {
  const half = (input.bandHigh - input.bandLow) / 2;
  const levels = input.step > 0 ? Math.floor(half / input.step + EPS) : 0;
  const clip = levels > 0 ? floorTo(input.swing / levels, input.sizeStep) : 0;
  return { levels, clip };
}

/** MS1–MS6, in the backend's words. Null when Start would go ahead. */
export function massagerRefusal(input: MassagerInput): string | null {
  const { bandLow: low, bandHigh: high, swing, step } = input;
  if (input.position === 0) return "A Massager needs an open Position";
  if (!(low > 0) || !(high > 0) || low >= high) {
    return "The Band needs a low below its high, both above 0";
  }
  if (input.mid != null && (input.mid < low - EPS || input.mid > high + EPS)) {
    return "Price is outside the Band";
  }
  if (!(swing > 0) || !(step > 0)) return "Set the Swing and the Step";
  const { levels, clip } = derive(input);
  if (levels < 1) return "The Step is wider than half the Band";
  if (!(clip > EPS) || clip + EPS < input.minQty) {
    return "The Clip comes out under the venue minimum: widen the Step or raise the Swing";
  }
  if (levels * clip >= Math.abs(input.position) - EPS) {
    return "The Swing must be smaller than the Core";
  }
  const center = (low + high) / 2;
  const need = (center * 2 * input.makerBps) / 10_000 + input.tick;
  if (step + EPS < need) return "A Step does not clear the fees: widen the Step";
  return null;
}

/** MS5, MS7, MS8: the lattice, the Position range and the catch-up. Null while refused. */
export function massagerPreview(input: MassagerInput): MassagerPreview | null {
  if (massagerRefusal(input) != null) return null;
  const { bandLow: low, bandHigh: high, step, position } = input;
  const { levels, clip } = derive(input);
  const swing = levels * clip;
  const center = (low + high) / 2;
  const prices: number[] = [];
  for (let k = -levels; k <= levels; k++) prices.push(roundToTick(center + k * step, input.tick));
  let level = 0;
  if (input.mid != null) {
    const offset = (input.mid - center) / step;
    level = offset >= 0 ? Math.floor(offset + EPS) : Math.ceil(offset - EPS);
    level = Math.max(-levels, Math.min(levels, level));
  }
  return {
    levels,
    clip,
    swing,
    center,
    step,
    prices,
    positionLow: position - swing,
    positionHigh: position + swing,
    perRoundTrip: clip * step,
    catchUp: {
      side: level > 0 ? "sell" : level < 0 ? "buy" : null,
      qty: Math.abs(level) * clip,
      level,
    },
  };
}

/** The working row's numbers, from the desk's snapshot. Position range is Core ∓ Swing. */
export function massagerRowFacts(algo: {
  core?: string | null;
  lean?: string | null;
  position?: string | null;
  qty?: string | null;
  captured_pnl?: string | null;
  massager_pnl?: string | null;
  tally_captured?: string | null;
  tally_runs?: number | null;
}): {
  core: number;
  lean: number;
  position: number;
  positionLow: number;
  positionHigh: number;
  captured: number;
  /** MS10: Captured plus the Lean marked at the mid; null while the desk has no mid. */
  pnl: number | null;
  /** MS20: the Tally's Captured over every run, and how many runs. */
  tallyCaptured: number;
  runs: number;
} {
  const num = (raw: string | null | undefined) => {
    const n = parseFloat(raw ?? "");
    return Number.isFinite(n) ? n : 0;
  };
  const core = num(algo.core);
  const lean = num(algo.lean);
  const swing = num(algo.qty);
  return {
    core,
    lean,
    position: algo.position != null && algo.position !== "" ? num(algo.position) : core + lean,
    positionLow: core - swing,
    positionHigh: core + swing,
    captured: num(algo.captured_pnl),
    pnl: algo.massager_pnl != null && algo.massager_pnl !== "" ? num(algo.massager_pnl) : null,
    tallyCaptured:
      algo.tally_captured != null && algo.tally_captured !== ""
        ? num(algo.tally_captured)
        : num(algo.captured_pnl),
    runs: algo.tally_runs ?? 1,
  };
}

/** What the preview needs, from the ticket and the live account. */
export function massagerInput(
  state: MassagerParamsState,
  {
    market,
    swing,
    position,
    mid,
    minQty,
    makerBps,
  }: {
    market: { price_decimals?: number | null; size_decimals?: number | null };
    swing: number;
    position: number;
    mid: number | null;
    minQty: number;
    makerBps: number;
  }
): MassagerInput {
  return {
    bandLow: parseDecimal(state.chaseFloor) ?? 0,
    bandHigh: parseDecimal(state.chaseCeiling) ?? 0,
    swing,
    step: parseDecimal(massagerStepRaw(state)) ?? 0,
    position,
    mid,
    tick: 10 ** -(market.price_decimals ?? 4),
    sizeStep: 10 ** -(market.size_decimals ?? 4),
    minQty,
    makerBps,
  };
}

/** MS19, MS21: ATR(14) on 15m, 1h or 4h candles; presets of ½, 1 and 2 × it. */
export const MASSAGER_ATR_LENGTH = 14;
export const MASSAGER_ATR_TIMEFRAMES: readonly MassagerAtrTf[] = ["15m", "1h", "4h"];
export const MASSAGER_ATR_MULTIPLES = [0.5, 1, 2] as const;
const TIMEFRAME_SEC: Record<MassagerAtrTf, number> = { "15m": 900, "1h": 3600, "4h": 14400 };

export function atrMultLabel(k: number): string {
  return k === 0.5 ? "½" : String(k);
}

/** MS21: ATR on the candles closed by now, as the desk reads it. Candle times are seconds. */
export function closedAtr(
  candles: readonly { time: number; high: number; low: number; close: number }[],
  timeframe: MassagerAtrTf,
  nowMs: number
): number | null {
  const period = TIMEFRAME_SEC[timeframe];
  return lastAtr(candles.filter((c) => (c.time + period) * 1000 <= nowMs));
}

/** The last ATR over the candles, Wilder's smoothing; null without enough of them. */
export function lastAtr(
  candles: readonly { high: number; low: number; close: number }[],
  length = MASSAGER_ATR_LENGTH
): number | null {
  const values = atr(
    candles.map((c) => c.high),
    candles.map((c) => c.low),
    candles.map((c) => c.close),
    length
  );
  const last = values[values.length - 1];
  return last != null && Number.isFinite(last) ? last : null;
}

/** MS18: the Massager already working this Market, if any: a second one is refused. */
export function runningMassager<T extends { algo_type?: string | null; symbol?: string | null }>(
  working: readonly T[],
  symbol: string
): T | null {
  return working.find((a) => a.algo_type === "massager" && a.symbol === symbol) ?? null;
}
