import type { AlgoBook, AlgoState, OpenOrder, PlannerPlan } from "@/lib/api";
import { algoIsWorking } from "@/lib/algos";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";

/** Planner's form. Rules live in docs/planner-rules.md; the desk has the last word. */

export type PlannerMode = "enter" | "attach";
export type PlannerSide = "buy" | "sell";
export type PlannerSizeMode = "size" | "risk";
export type PlannerStopSteps = "off" | "breakeven" | "ladder";

export type PlannerTargetOrder = "limit" | "trigger";

export interface PlannerTargetDraft {
  kind: "r" | "price";
  /** P9: a resting reduce-only Limit, or a Trigger that waits off the book. */
  order: PlannerTargetOrder;
  value: string;
  pct: string;
}

export interface PlannerForm {
  side: PlannerSide;
  entryType: "market" | "limit";
  entryPrice: string;
  stop: string;
  sizeMode: PlannerSizeMode;
  size: string;
  riskPct: string;
  targets: PlannerTargetDraft[];
  stopSteps: PlannerStopSteps;
  expiryMin: string;
}

export const MAX_TARGETS = 5;

export function defaultPlannerForm(side: PlannerSide = "buy"): PlannerForm {
  return {
    side,
    entryType: "limit",
    entryPrice: "",
    stop: "",
    sizeMode: "risk",
    size: "",
    riskPct: "1",
    targets: [
      { kind: "r", value: "2", pct: "50", order: "limit" },
      { kind: "r", value: "3", pct: "50", order: "limit" },
    ],
    stopSteps: "breakeven",
    expiryMin: "",
  };
}

function num(raw: string): number {
  return parseDecimal(raw) ?? NaN;
}

/** P5: what no target closes rides on the stop. */
export function runnerPct(targets: PlannerTargetDraft[]): number {
  const total = targets.reduce((s, t) => s + (num(t.pct) || 0), 0);
  return Math.max(0, 100 - total);
}

/** First thing that stops the form from being sent, before the desk is asked. */
export function plannerFormBlock(form: PlannerForm, mode: PlannerMode): string | null {
  if (!(num(form.stop) > 0)) return "Set a stop";
  if (mode === "enter") {
    if (form.entryType === "limit" && !(num(form.entryPrice) > 0)) return "Set the entry price";
    if (form.sizeMode === "size" && !(num(form.size) > 0)) return "Set a size";
    if (form.sizeMode === "risk" && !(num(form.riskPct) > 0)) return "Set the risk %";
  }
  if (form.targets.length === 0) return "Add a target";
  for (const t of form.targets) {
    if (!(num(t.value) > 0)) return t.kind === "r" ? "Set each target's R" : "Set each target's price";
    if (!(num(t.pct) > 0)) return "Each target closes more than 0%";
  }
  if (form.targets.reduce((s, t) => s + num(t.pct), 0) > 100 + 1e-9) {
    return "Targets add up to more than 100%";
  }
  return null;
}

export function plannerBody(
  form: PlannerForm,
  opts: { mode: PlannerMode; marketIndex: number; slippage: number }
): Record<string, unknown> {
  const dec = (raw: string) => canonicalDecimal(raw) ?? raw;
  const enter = opts.mode === "enter";
  const expiry = parseInt(form.expiryMin, 10);
  return {
    market_index: opts.marketIndex,
    mode: opts.mode,
    side: form.side,
    entry_type: form.entryType,
    entry_price: enter && form.entryType === "limit" ? dec(form.entryPrice) : null,
    stop: dec(form.stop),
    size: enter && form.sizeMode === "size" ? dec(form.size) : null,
    risk_pct: enter && form.sizeMode === "risk" ? dec(form.riskPct) : null,
    targets: form.targets.map((t) => ({
      kind: t.kind,
      value: dec(t.value),
      pct: dec(t.pct),
      order: t.order,
    })),
    stop_steps: form.stopSteps,
    expiry_min: enter && form.entryType === "limit" && expiry > 0 ? expiry : null,
    slippage: opts.slippage,
  };
}

/** Re-plan starts from what the running Planner already holds. */
export function formFromPlanner(algo: AlgoState): PlannerForm {
  const p = (algo.params_json ?? {}) as Record<string, unknown>;
  const targets = Array.isArray(p.targets) ? (p.targets as Record<string, unknown>[]) : [];
  const stop = algo.planner?.stop_trigger ?? (typeof p.stop === "string" ? p.stop : "");
  return {
    ...defaultPlannerForm(algo.side === "sell" ? "sell" : "buy"),
    stop: stop ?? "",
    targets: targets.map((t) => ({
      kind: t.kind === "price" ? "price" : "r",
      value: String(t.value ?? ""),
      pct: String(t.pct ?? ""),
      order: t.order === "limit" ? "limit" : "trigger",
    })),
    stopSteps:
      p.stop_steps === "off" || p.stop_steps === "breakeven" || p.stop_steps === "ladder"
        ? p.stop_steps
        : p.breakeven === false
          ? "off"
          : "breakeven",
  };
}

export function livePlannerFor(
  book: AlgoBook | null | undefined,
  marketIndex: number | null | undefined
): AlgoState | undefined {
  if (!book || marketIndex == null) return undefined;
  return book.working.find(
    (a) =>
      a.algo_type === "planner" && a.market_index === marketIndex && algoIsWorking(a.status)
  );
}

/** "Stop", "TP1", "Entry"… for a Planner Clip, by its client_order_index. */
export function plannerClipLabel(
  algo: AlgoState | undefined,
  coi: string | number | null | undefined
): string | null {
  if (!algo || coi == null) return null;
  const role = algo.planner?.clip_roles?.[String(coi)];
  if (!role) return null;
  if (role === "stop") return stopLabel(algo);
  if (role === "entry") return "Entry";
  if (role === "close") return "Close";
  if (role.startsWith("tp") && /^tp\d+$/.test(role)) return role.toUpperCase();
  return "TP";
}

export function plannerPhaseLabel(algo: AlgoState): string {
  const rt = algo.planner;
  if (algo.status === "paused") return "Paused";
  if (algo.status === "error") return "Error";
  if (algo.status === "done") return "Done";
  if (algo.status === "stopped") return "Stopped";
  if (!rt) return "Running";
  if (rt.phase === "entering") return "Entering";
  const at = stepReached(algo);
  return at ? `At ${at}` : "Managing";
}

function stepsDone(algo: AlgoState): number {
  const rt = algo.planner;
  if (!rt) return 0;
  return rt.steps_done ?? (rt.breakeven_done ? 1 : 0);
}

/** Where the stop has stepped to: "breakeven", "TP1"…, or null before any step. */
export function stepReached(algo: AlgoState): string | null {
  const done = stepsDone(algo);
  if (done <= 0) return null;
  const step = algo.planner?.plan?.steps?.find((s) => s.after === done);
  if (!step || step.to === "breakeven") return "breakeven";
  return step.to.toUpperCase();
}

export function stopLabel(algo: AlgoState): string {
  const at = stepReached(algo);
  if (!at) return "Stop";
  return at === "breakeven" ? "BE stop" : `Stop at ${at}`;
}

/** P8-style: how far a step leaves the stop below (long) the target that took it. */
export function stepGapPct(plan: PlannerPlan, after: number, price: string): string | null {
  const target = plan.targets.find((t) => t.index === after);
  const tp = parseFloat(target?.price ?? "");
  const px = parseFloat(price);
  if (!(tp > 0) || !(px > 0)) return null;
  const gap = ((px - tp) / tp) * 100 * (plan.side === "buy" ? 1 : -1);
  return signedPct(String(gap), 2);
}

export function stepTargetLabel(to: string): string {
  return to === "breakeven" ? "breakeven" : to.toUpperCase();
}

export function signedPct(raw: string | null | undefined, digits = 2): string {
  const n = parseFloat(raw ?? "");
  if (!Number.isFinite(n)) return "—";
  const s = Math.abs(n).toFixed(digits);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${s}%`;
}

export function rLabel(raw: string | null | undefined): string {
  const n = parseFloat(raw ?? "");
  if (!Number.isFinite(n)) return "—";
  return `${Number(n.toFixed(2))}R`;
}

/** Filled targets of a running Planner, counted from its Clips. */
export function plannerTargetsDone(algo: AlgoState): number {
  const roles = algo.planner?.clip_roles ?? {};
  return (algo.clips ?? []).filter(
    (c) => /^tp\d+$/.test(roles[String(c.client_order_index)] ?? "") && c.status === "filled"
  ).length;
}

/** S6: the Tickets an Attach replaces, as a line for the confirm. */
export function replacedLine(orders: OpenOrder[]): string | null {
  if (orders.length === 0) return null;
  const parts = orders.map((o) => {
    const kind = /stop/i.test(o.order_type) ? "Stop" : "Take Profit";
    return `${kind} ${o.trigger_price || o.price}`;
  });
  return `Replaces ${parts.join(", ")}`;
}

export function planSummary(plan: PlannerPlan): string {
  return `R ${plan.r} · risk $${Number(parseFloat(plan.risk_usd).toFixed(2))}`;
}
