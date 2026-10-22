import type { Idea, IdeaAlert } from "@/lib/api.gen";

/** docs/idea-rules.md A1. */
export const ALERTS_PER_IDEA = 20;

const MINUS = "−";

function wayPct(alert: Pick<IdeaAlert, "direction" | "pct">): string {
  const mark = alert.direction === "up" ? "+" : alert.direction === "down" ? MINUS : "±";
  return `${mark}${alert.pct ?? ""}%`;
}

/** What the alert waits for, in a few words: "Above 2.20", "Moves ±5% from 2.15", "Daily Change +10%". */
export function alertWhat(alert: IdeaAlert): string {
  if (alert.kind === "level") return `${alert.direction === "above" ? "Above" : "Below"} ${alert.price ?? ""}`;
  if (alert.kind === "move") return `Moves ${wayPct(alert)} from ${alert.base ?? "?"}`;
  return `Daily Change ${wayPct(alert)}`;
}

/** An armed Level's distance from Last, in percent of Last. Positive: price must rise to it. */
export function alertDistancePct(alert: IdeaAlert, last: number | null): number | null {
  if (alert.kind !== "level" || alert.status !== "armed" || last == null || !(last > 0)) return null;
  const level = Number(alert.price);
  if (!(level > 0)) return null;
  return ((level - last) / last) * 100;
}

export function armedCount(alerts: IdeaAlert[]): number {
  return alerts.filter((alert) => alert.status === "armed").length;
}

/** A10 runs only with a Plan price to watch. */
export function hasPlanPrice(idea: Pick<Idea, "entry_low" | "entry_high" | "stop" | "targets">): boolean {
  return Boolean((idea.entry_low && idea.entry_high) || idea.stop || idea.targets.length);
}

/** A6: alerts on a Closed or Dropped Idea wait. */
export function alertsPaused(idea: Pick<Idea, "status">): boolean {
  return idea.status === "closed" || idea.status === "dropped";
}
