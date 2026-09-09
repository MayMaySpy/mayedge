import type { LiquidationEvent } from "@/lib/api";

export function liqUsd(l: Pick<LiquidationEvent, "usd_amount" | "price" | "size">): number {
  const u = parseFloat(l.usd_amount ?? "");
  if (Number.isFinite(u) && u > 0) return u;
  const px = parseFloat(l.price);
  const sz = parseFloat(l.size);
  if (Number.isFinite(px) && Number.isFinite(sz)) return Math.abs(px * sz);
  return 0;
}

/** True when notional meets a user-set significant floor. */
export function isSignificantLiq(usd: number, minNotional: number): boolean {
  return Number.isFinite(minNotional) && minNotional > 0 && usd >= minNotional;
}
