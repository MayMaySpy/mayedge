/** Client preview of chase-iceberg. Engine of record is Python + golden vectors. */

export const CHASE_ID = "chase-iceberg";
export const CHASE_VERSION = "1";

export type ChaseAction = "rest" | "pause" | "done";

export function roundPassive(price: number, tick: number, side: "buy" | "sell"): number {
  if (!(tick > 0) || !(price > 0)) return price;
  const steps = price / tick;
  const n = side === "buy" ? Math.floor(steps + 1e-12) : Math.ceil(steps - 1e-12);
  return n * tick;
}

export function clipQty(remaining: number, displayQty: number, qtyStep = 0): number {
  let clip = Math.min(displayQty, remaining);
  if (qtyStep > 0) {
    const n = Math.floor(clip / qtyStep + 1e-12);
    clip = n * qtyStep;
  }
  return clip;
}

export function chaseQuote(opts: {
  side: "buy" | "sell";
  remaining: number;
  displayQty: number;
  offsetBps: number;
  floor: number;
  ceiling: number;
  bid: number | null;
  ask: number | null;
  tick: number;
  minQty: number;
  qtyStep?: number;
}): { action: ChaseAction; price: number | null; qty: number | null; reason: string | null } {
  const { side, remaining, displayQty, offsetBps, floor, ceiling, bid, ask, tick, minQty, qtyStep = 0 } =
    opts;
  if (!(remaining > 0)) return { action: "done", price: null, qty: null, reason: "filled" };
  const clip = clipQty(remaining, displayQty, qtyStep);
  if (!(clip >= minQty) || !(clip > 0)) {
    return { action: "pause", price: null, qty: null, reason: "below_min_qty" };
  }
  if (bid == null || ask == null || !(bid > 0) || !(ask > 0) || !(tick > 0)) {
    return { action: "pause", price: null, qty: null, reason: "no_book" };
  }
  if (!(floor < ceiling) || offsetBps < 0) {
    return { action: "pause", price: null, qty: null, reason: "invalid_band" };
  }
  const offset = offsetBps / 10_000;
  if (side === "buy") {
    if (bid < floor) return { action: "pause", price: null, qty: null, reason: "below_floor" };
    let px = bid > ceiling ? roundPassive(ceiling, tick, "buy") : roundPassive(bid * (1 - offset), tick, "buy");
    if (px > ceiling) px = roundPassive(ceiling, tick, "buy");
    if (px < floor) return { action: "pause", price: null, qty: null, reason: "below_floor" };
    if (px >= ask) return { action: "pause", price: null, qty: null, reason: "would_cross" };
    return { action: "rest", price: px, qty: clip, reason: null };
  }
  if (ask > ceiling) return { action: "pause", price: null, qty: null, reason: "above_ceiling" };
  let px = ask < floor ? roundPassive(floor, tick, "sell") : roundPassive(ask * (1 + offset), tick, "sell");
  if (px < floor) px = roundPassive(floor, tick, "sell");
  if (px > ceiling) return { action: "pause", price: null, qty: null, reason: "above_ceiling" };
  if (px <= bid) return { action: "pause", price: null, qty: null, reason: "would_cross" };
  return { action: "rest", price: px, qty: clip, reason: null };
}
