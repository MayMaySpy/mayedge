/** The viewer's Day open: local midnight today, in ms (docs/portfolio-rules.md N1). */
export function localMidnightMs(now = new Date()): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export const PORTFOLIO_KIND_LABELS = {
  perps: "Perps",
  spot: "Spot",
  llp: "LLP",
  staking: "Staking",
} as const;
