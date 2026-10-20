import type { PortfolioKind, PortfolioNow } from "@/lib/api";

/** The Day open: 00:00 UTC today, in ms. The desk never uses local time (docs/portfolio-rules.md N1). */
export function utcMidnightMs(now = Date.now()): number {
  return now - (now % 86_400_000);
}

/** Stack and legend order. Never re-sorted by size, so a kind keeps its color. */
export const PORTFOLIO_KINDS = ["perps", "spot", "llp", "staking"] as const;

/**
 * One hue per Holding kind, fixed. Validated with the dataviz palette checks on the
 * desk panel (#141c26, dark): all adjacent pairs pass CVD and normal-vision separation.
 * Green and red are left out: on this desk they mean gain and loss.
 */
export const PORTFOLIO_KIND_COLORS = {
  perps: "#3987e5",
  spot: "#d95926",
  llp: "#9085e9",
  staking: "#c98500",
} as const;

export const PORTFOLIO_KIND_LABELS = {
  perps: "Perps",
  spot: "Spot",
  llp: "LLP",
  staking: "Staking",
} as const;

/** The kinds that held money at any point in a value history, plus any held now. In stack order. */
export function historyKinds(points: Partial<Record<PortfolioKind, string | null>>[], now: PortfolioKind[]): PortfolioKind[] {
  return PORTFOLIO_KINDS.filter((k) => now.includes(k) || points.some((p) => Number(p[k] ?? "0") !== 0));
}

/** The kinds worth a row: held now, at the open, or moved since it. In stack order. */
export function heldKinds(now: PortfolioNow): PortfolioKind[] {
  return PORTFOLIO_KINDS.filter((k) => {
    const kind = now.kinds[k];
    return [kind.value, kind.value_at_open, kind.change, kind.flows].some((v) => Number(v ?? "0") !== 0);
  });
}
