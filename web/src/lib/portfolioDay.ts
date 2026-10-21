import type { PortfolioKind, PortfolioNow } from "@/lib/api";
import { formatUsd } from "@/lib/utils";

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

/** W4: what happened at one moment: money in or out of the account, or moved between kinds. */
export type FlowEvent = {
  ts: number;
  kind: "move" | "in" | "out";
  /** The kind that held the money after (in, move) or before (out): its color marks the event. */
  color: string;
  label: string;
};

/** Under a dollar of net Flow at one moment is a move between kinds, not money in or out. */
const MOVE_TOLERANCE_USD = 1;

/**
 * W4: one event per moment. A moment whose Flows cancel out (LLP −539, Perps +539) is a
 * move between kinds; otherwise the net is a deposit or a withdrawal.
 */
export function flowEvents(flows: { ts: number; kind: PortfolioKind; amount: string | null }[]): FlowEvent[] {
  const byTs = new Map<number, { kind: PortfolioKind; amount: number }[]>();
  for (const f of flows) {
    const amount = Number(f.amount ?? "0");
    if (!Number.isFinite(amount) || amount === 0) continue;
    byTs.set(f.ts, [...(byTs.get(f.ts) ?? []), { kind: f.kind, amount }]);
  }
  const usd = (n: number) => formatUsd(Math.abs(n));
  const names = (parts: { kind: PortfolioKind }[]) => parts.map((p) => PORTFOLIO_KIND_LABELS[p.kind]).join(", ");
  return [...byTs.entries()]
    .sort(([a], [b]) => a - b)
    .map(([ts, parts]) => {
      const net = parts.reduce((s, p) => s + p.amount, 0);
      const into = parts.filter((p) => p.amount > 0);
      const outOf = parts.filter((p) => p.amount < 0);
      if (into.length && outOf.length && Math.abs(net) < MOVE_TOLERANCE_USD) {
        const moved = into.reduce((s, p) => s + p.amount, 0);
        return {
          ts,
          kind: "move",
          color: PORTFOLIO_KIND_COLORS[into[0].kind],
          label: `Moved ${usd(moved)} ${names(outOf)} → ${names(into)}`,
        };
      }
      const side = net > 0 ? into : outOf;
      const lead = (side[0] ?? parts[0]).kind;
      return {
        ts,
        kind: net > 0 ? "in" : "out",
        color: PORTFOLIO_KIND_COLORS[lead],
        label: `${net > 0 ? "Deposit" : "Withdrawal"} ${usd(net)} ${net > 0 ? "into" : "from"} ${names(side.length ? side : parts)}`,
      };
    });
}
