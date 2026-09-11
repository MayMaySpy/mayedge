export const LADDER_MIN_ORDERS = 2;
export const LADDER_MAX_ORDERS = 100;
export const LADDER_MAX_VAR_PCT = 50;
/** Low/High chips → 3:1 size ramp (matches backend SKEW_STRENGTH). */
export const LADDER_SKEW_STRENGTH = 0.5;

export type LadderPlanSide = "buy" | "sell";

export type LadderPlanOrder = {
  price: number;
  qty: number;
};

export type LadderPlan = {
  orders: LadderPlanOrder[];
  qty: number;
  avgEntry: number;
};

export type LadderPlanInput = {
  side?: LadderPlanSide | null;
  qty: number;
  priceFrom: number;
  priceTo: number;
  orders: number;
  tick: number;
  qtyStep: number;
  minQty: number;
  sizeVarPct?: number;
  priceVarPct?: number;
  /** -1 more size at low prices, 0 even, +1 more size at high prices. */
  sizeSkew?: number;
  seed?: number;
};

/** Numeric LCG — same constants as backend `NumericLcg`. */
export function createLadderRng(seed: number) {
  let state = seed >>> 0;
  return {
    uniform(a: number, b: number) {
      state = (Math.imul(1664525, state) + 1013904223) >>> 0;
      return a + (b - a) * (state / 4294967296);
    },
  };
}

function roundToTick(price: number, tick: number, side: LadderPlanSide): number {
  if (!(tick > 0)) return price;
  const steps = price / tick;
  const n = side === "buy" ? Math.floor(steps + 1e-12) : Math.ceil(steps - 1e-12);
  return n * tick;
}

function roundQty(qty: number, step: number): number {
  if (!(step > 0)) return qty;
  return Math.floor(qty / step + 1e-12) * step;
}

function gapWeights(
  n: number,
  varFrac: number,
  rng: { uniform: (a: number, b: number) => number } | null
): number[] {
  if (n <= 0) return [];
  if (!(varFrac > 0) || !rng) return Array.from({ length: n }, () => 1 / n);
  const raw = Array.from({ length: n }, () => Math.max(0.05, 1 + rng.uniform(-varFrac, varFrac)));
  const total = raw.reduce((s, w) => s + w, 0);
  if (!(total > 0)) return Array.from({ length: n }, () => 1 / n);
  return raw.map((w) => w / total);
}

function sizeWeights(
  prices: number[],
  skew: number,
  varFrac: number,
  rng: { uniform: (a: number, b: number) => number } | null
): number[] {
  const n = prices.length;
  if (n <= 0) return [];
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  const span = hi - lo;
  const strength = Math.abs(skew) * LADDER_SKEW_STRENGTH;
  const raw = prices.map((p) => {
    const t = span === 0 ? 0.5 : (p - lo) / span;
    const towardHigh = skew >= 0 ? t : 1 - t;
    let w = 1 - strength + 2 * strength * towardHigh;
    if (varFrac > 0 && rng) {
      w *= Math.max(0.05, 1 + rng.uniform(-varFrac, varFrac));
    }
    return Math.max(0.05, w);
  });
  const total = raw.reduce((s, w) => s + w, 0);
  if (!(total > 0)) return Array.from({ length: n }, () => 1 / n);
  return raw.map((w) => w / total);
}

function planSide(input: LadderPlanInput): LadderPlanSide {
  if (input.side === "buy" || input.side === "sell") return input.side;
  return input.priceFrom >= input.priceTo ? "buy" : "sell";
}

function alignedFromTo(input: LadderPlanInput, side: LadderPlanSide): { from: number; to: number } {
  const lo = Math.min(input.priceFrom, input.priceTo);
  const hi = Math.max(input.priceFrom, input.priceTo);
  return side === "buy" ? { from: hi, to: lo } : { from: lo, to: hi };
}

export function buildLadderPlan(input: LadderPlanInput): LadderPlan | { error: string } {
  const side = planSide(input);
  const count = Math.round(input.orders);
  if (!(input.qty > 0)) return { error: "Enter size" };
  if (count < LADDER_MIN_ORDERS || count > LADDER_MAX_ORDERS) {
    return { error: `Orders ${LADDER_MIN_ORDERS}–${LADDER_MAX_ORDERS}` };
  }
  if (!(input.priceFrom > 0) || !(input.priceTo > 0) || input.priceFrom === input.priceTo) {
    return { error: "Set from / to prices" };
  }
  const sizeVar = Math.max(0, input.sizeVarPct ?? 0);
  const priceVar = Math.max(0, input.priceVarPct ?? 0);
  const skew = input.sizeSkew ?? 0;
  if (sizeVar > LADDER_MAX_VAR_PCT || priceVar > LADDER_MAX_VAR_PCT) {
    return { error: `Variance 0–${LADDER_MAX_VAR_PCT}%` };
  }
  if (skew < -1 || skew > 1) return { error: "Skew must be even, low, or high" };
  const even = roundQty(input.qty / count, input.qtyStep);
  if (!(even > 0)) return { error: "Too many orders for size" };
  if (input.minQty > 0 && even + 1e-12 < input.minQty) {
    return { error: "Each order is below min size" };
  }

  const { from, to } = alignedFromTo(input, side);
  const sizeFrac = sizeVar / 100;
  const priceFrac = priceVar / 100;
  const rng =
    sizeFrac > 0 || priceFrac > 0 ? createLadderRng(input.seed ?? 1) : null;

  const gaps = gapWeights(count - 1, priceFrac, rng);
  const span = to - from;
  const rawPrices: number[] = [from];
  let acc = 0;
  gaps.forEach((w, i) => {
    acc += w;
    rawPrices.push(i === gaps.length - 1 ? to : from + span * acc);
  });

  const unique: number[] = [];
  const seen = new Set<number>();
  for (const raw of rawPrices) {
    const price = roundToTick(raw, input.tick, side);
    if (seen.has(price)) continue;
    seen.add(price);
    unique.push(price);
  }
  if (!unique.length) return { error: "No valid orders after tick alignment" };

  const weights = sizeWeights(unique, skew, sizeFrac, rng);
  const orders: LadderPlanOrder[] = [];
  let allocated = 0;
  const last = unique.length - 1;
  for (let i = 0; i < unique.length; i++) {
    const qty =
      i === last
        ? roundQty(input.qty - allocated, input.qtyStep)
        : roundQty(input.qty * weights[i], input.qtyStep);
    if (!(qty > 0)) continue;
    if (input.minQty > 0 && qty + 1e-12 < input.minQty) {
      return { error: "Each order is below min size" };
    }
    allocated += qty;
    orders.push({ price: unique[i], qty });
  }
  if (!orders.length) return { error: "Too many orders for size" };
  const remainder = input.qty - orders.reduce((s, o) => s + o.qty, 0);
  if (remainder !== 0) {
    const patched = orders[orders.length - 1].qty + remainder;
    if (!(patched > 0) || (input.minQty > 0 && patched + 1e-12 < input.minQty)) {
      return { error: "Too many orders for size" };
    }
    orders[orders.length - 1] = { ...orders[orders.length - 1], qty: patched };
  }
  const qty = orders.reduce((s, o) => s + o.qty, 0);
  const avgEntry = qty > 0 ? orders.reduce((s, o) => s + o.price * o.qty, 0) / qty : 0;
  return { orders, qty, avgEntry };
}
