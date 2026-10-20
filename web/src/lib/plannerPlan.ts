import type { AlgoBook, AlgoState, OpenOrder, PlannerPlan } from "@/lib/api";
import { algoIsWorking } from "@/lib/algos";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";

/** Planner's form. Rules live in docs/planner-rules.md; the desk has the last word. */

export type PlannerMode = "enter" | "attach";
export type PlannerSide = "buy" | "sell";
export type PlannerSizeMode = "size" | "risk";
export type PlannerStopSteps = "off" | "breakeven" | "ladder";

export type PlannerTargetOrder = "limit" | "trigger" | "trail";
export type PlannerEntryType = "market" | "limit" | "trail" | "chase" | "ladder";
export type PlannerLadderStrength = "even" | "low" | "high";
export type PlannerTrailUnit = "r" | "pct";
export type PlannerTrailStopStart = "off" | "target" | "last" | "r";

export interface PlannerTargetDraft {
  kind: "r" | "price";
  /** P9: a resting reduce-only Limit, a Trigger that waits off the book, or a Trail. */
  order: PlannerTargetOrder;
  value: string;
  pct: string;
  /** A Trail target: how far behind the best price it follows once its price is reached. */
  trailDistance?: string;
  trailUnit?: PlannerTrailUnit;
}

/** E9: a Trail entry, held by the desk until the price comes back. */
export interface PlannerEntryTrailDraft {
  distance: string;
  distanceKind: "pct" | "price";
  activation: string;
}

/** E10: a Chase entry, worked behind the touch inside its band. */
export interface PlannerEntryChaseDraft {
  low: string;
  high: string;
  offsetBps: string;
  /** The most one Clip shows; empty works the whole size at once. */
  clip: string;
}

/** EL1: a Ladder entry, every rung resting at once from one price to another. */
export interface PlannerEntryLadderDraft {
  from: string;
  to: string;
  rungs: string;
  /** Like the Ladder algo's skew: more size toward the low or the high price. */
  strength: PlannerLadderStrength;
}

/** EL4: the desk's cap of live algo orders on one Market. */
export const PLANNER_LADDER_MIN_RUNGS = 2;
export const PLANNER_LADDER_MAX_RUNGS = 20;

const STRENGTH_SKEW: Record<PlannerLadderStrength, string> = { even: "0", low: "-1", high: "1" };

/** M10: when the stop starts to trail, and how far behind the best price. */
export interface PlannerTrailStopDraft {
  start: PlannerTrailStopStart;
  after: string;
  atR: string;
  distance: string;
  unit: PlannerTrailUnit;
}

export interface PlannerForm {
  side: PlannerSide;
  entryType: PlannerEntryType;
  entryTrail: PlannerEntryTrailDraft;
  entryChase: PlannerEntryChaseDraft;
  entryLadder: PlannerEntryLadderDraft;
  trailStop: PlannerTrailStopDraft;
  reference: "mark" | "last";
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
    entryTrail: { distance: "1", distanceKind: "pct", activation: "" },
    entryChase: { low: "", high: "", offsetBps: "4", clip: "" },
    entryLadder: { from: "", to: "", rungs: "5", strength: "even" },
    trailStop: { start: "off", after: "1", atR: "2", distance: "1", unit: "r" },
    reference: "mark",
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
    if (form.entryType === "trail" && !(num(form.entryTrail.distance) > 0)) {
      return "Set the Trail entry's distance";
    }
    if (form.entryType === "chase") {
      const low = num(form.entryChase.low);
      const high = num(form.entryChase.high);
      if (!(low > 0) || !(high > 0)) return "Set the Chase band";
      if (!(high > low)) return "The band's low must be under its high";
      if (!(num(form.entryChase.offsetBps) >= 0)) return "Set the offset";
    }
    if (form.entryType === "ladder") {
      const from = num(form.entryLadder.from);
      const to = num(form.entryLadder.to);
      if (!(from > 0) || !(to > 0)) return "Set the Ladder's from and to";
      if (from === to) return "The Ladder's from and to must differ";
      const rungs = Number(form.entryLadder.rungs);
      if (!Number.isInteger(rungs) || rungs < PLANNER_LADDER_MIN_RUNGS || rungs > PLANNER_LADDER_MAX_RUNGS) {
        return `A Ladder has ${PLANNER_LADDER_MIN_RUNGS} to ${PLANNER_LADDER_MAX_RUNGS} rungs`;
      }
    }
    if (form.sizeMode === "size" && !(num(form.size) > 0)) return "Set a size";
    if (form.sizeMode === "risk" && !(num(form.riskPct) > 0)) return "Set the risk %";
  }
  const trailing = form.trailStop.start !== "off";
  if (trailing) {
    if (!(num(form.trailStop.distance) > 0)) return "Set the trail stop's distance";
    if (form.trailStop.start === "r" && !(num(form.trailStop.atR) > 0)) {
      return "Set the R the stop starts trailing at";
    }
    if (form.trailStop.start === "target") {
      const n = parseInt(form.trailStop.after, 10);
      if (!(n >= 1 && n <= form.targets.length)) return "Pick the target the stop trails after";
    }
  }
  if (form.targets.length === 0 && !trailing) return "Add a target, or trail the stop";
  for (const t of form.targets) {
    if (!(num(t.value) > 0)) return t.kind === "r" ? "Set each target's R" : "Set each target's price";
    if (!(num(t.pct) > 0)) return "Each target closes more than 0%";
    if (t.order === "trail" && !(num(t.trailDistance ?? "") > 0)) {
      return "Set each Trail target's distance";
    }
  }
  if (form.targets.reduce((s, t) => s + num(t.pct), 0) > 100 + 1e-9) {
    return "Targets add up to more than 100%";
  }
  return null;
}

/** Does any part of this plan follow the price? */
export function plannerTrails(form: PlannerForm): boolean {
  return (
    form.entryType === "trail" ||
    form.trailStop.start !== "off" ||
    form.targets.some((t) => t.order === "trail")
  );
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
    entry_trail:
      enter && form.entryType === "trail"
        ? {
            distance: dec(form.entryTrail.distance),
            distance_kind: form.entryTrail.distanceKind,
            activation: canonicalDecimal(form.entryTrail.activation) ?? null,
          }
        : null,
    trail_stop:
      form.trailStop.start === "off"
        ? null
        : {
            start: form.trailStop.start,
            after: parseInt(form.trailStop.after, 10) || 1,
            at_r: form.trailStop.start === "r" ? dec(form.trailStop.atR) : null,
            distance: dec(form.trailStop.distance),
            unit: form.trailStop.unit,
          },
    entry_chase:
      enter && form.entryType === "chase"
        ? {
            low: dec(form.entryChase.low),
            high: dec(form.entryChase.high),
            offset_bps: dec(form.entryChase.offsetBps),
            clip: canonicalDecimal(form.entryChase.clip) ?? null,
          }
        : null,
    entry_ladder:
      enter && form.entryType === "ladder"
        ? {
            price_from: dec(form.entryLadder.from),
            price_to: dec(form.entryLadder.to),
            rungs: parseInt(form.entryLadder.rungs, 10),
            strength: STRENGTH_SKEW[form.entryLadder.strength],
          }
        : null,
    reference: form.reference,
    stop: dec(form.stop),
    size: enter && form.sizeMode === "size" ? dec(form.size) : null,
    risk_pct: enter && form.sizeMode === "risk" ? dec(form.riskPct) : null,
    targets: form.targets.map((t) => ({
      kind: t.kind,
      value: dec(t.value),
      pct: dec(t.pct),
      order: t.order,
      ...(t.order === "trail"
        ? { trail_distance: dec(t.trailDistance ?? ""), trail_unit: t.trailUnit ?? "r" }
        : {}),
    })),
    stop_steps: form.stopSteps,
    expiry_min: enter && form.entryType !== "market" && expiry > 0 ? expiry : null,
    slippage: opts.slippage,
  };
}

/** Re-plan starts from what the running Planner already holds. */
export function formFromPlanner(algo: AlgoState): PlannerForm {
  const p = (algo.params_json ?? {}) as Record<string, unknown>;
  const targets = Array.isArray(p.targets) ? (p.targets as Record<string, unknown>[]) : [];
  const stop = algo.planner?.stop_trigger ?? (typeof p.stop === "string" ? p.stop : "");
  const base = defaultPlannerForm(algo.side === "sell" ? "sell" : "buy");
  const ts = (p.trail_stop ?? null) as Record<string, unknown> | null;
  const start = ts?.start;
  return {
    ...base,
    stop: stop ?? "",
    reference: p.reference === "last" ? "last" : "mark",
    trailStop:
      ts && (start === "target" || start === "last" || start === "r")
        ? {
            start,
            after: String(ts.after ?? "1"),
            atR: String(ts.at_r ?? "2"),
            distance: String(ts.distance ?? "1"),
            unit: ts.unit === "pct" ? "pct" : "r",
          }
        : base.trailStop,
    targets: targets.map((t) => ({
      kind: t.kind === "price" ? "price" : "r",
      value: String(t.value ?? ""),
      pct: String(t.pct ?? ""),
      order: t.order === "limit" ? "limit" : t.order === "trail" ? "trail" : "trigger",
      ...(t.order === "trail"
        ? {
            trailDistance: String(t.trail_distance ?? ""),
            trailUnit: t.trail_unit === "pct" ? ("pct" as const) : ("r" as const),
          }
        : {}),
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
  if (rt.phase === "entering") return entryLabel(algo);
  const at = stepReached(algo);
  return at ? `At ${at}` : "Managing";
}

/** "Entering", or "Chasing 0.6 / 2" while a Chase or Ladder entry fills in pieces. */
export function entryLabel(algo: AlgoState): string {
  const p = (algo.params_json ?? {}) as Record<string, unknown>;
  const verb = p.entry_type === "chase" ? "Chasing" : p.entry_type === "ladder" ? "Laddering" : null;
  if (!verb) return "Entering";
  return `${verb} ${algo.filled ?? "0"} / ${algo.qty ?? "—"}`;
}

/** E14: the entry can be ended early while it is still working. */
export function canProtectNow(algo: AlgoState): boolean {
  return algo.planner?.phase === "entering" && algoIsWorking(algo.status);
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

/** Dollars with their sign, to the cent: +$10.54, −$5.27. */
export function signedUsd(n: number): string {
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`;
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
