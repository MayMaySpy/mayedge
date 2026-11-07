/**
 * The Massager's ticket preview. It mirrors the backend planner
 * (backend/src/mayedge/algos/massager/plan.py, docs/massager-rules.md MS1–MS8)
 * so the ticket can say what Start would do. The backend still decides.
 */

import { atr } from "@/lib/mayRekt";
import { parseDecimal } from "@/lib/numbers";

/** The ticket's own fields. Size is the Swing. */
export interface MassagerParamsState {
  step: string;
  chaseFloor: string;
  chaseCeiling: string;
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
}): {
  core: number;
  lean: number;
  position: number;
  positionLow: number;
  positionHigh: number;
  captured: number;
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
    step: parseDecimal(state.step) ?? 0,
    position,
    mid,
    tick: 10 ** -(market.price_decimals ?? 4),
    sizeStep: 10 ** -(market.size_decimals ?? 4),
    minQty,
    makerBps,
  };
}

/** MS19: the Step presets, as multiples of ATR(14) on 1h candles. */
export const MASSAGER_ATR_LENGTH = 14;
export const MASSAGER_ATR_RESOLUTION = "1h";
export const MASSAGER_ATR_MULTIPLES = [0.5, 1, 2] as const;

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
