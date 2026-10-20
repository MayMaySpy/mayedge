import { useSyncExternalStore } from "react";

import type { ChartOverlay } from "@/lib/chartTradingLines";
import { defaultPlannerForm, type PlannerForm } from "@/lib/plannerPlan";
import { snapTick } from "@/lib/ticketAmend";
import { theme } from "@/lib/theme";

/** A Planner sketched on the chart. No orders behind it (ADR 0018). */
export interface ChartDraft {
  entry: number | null;
  stop: number | null;
  targets: { r: string; pct: string }[];
}

export function defaultDraftTargets(): { r: string; pct: string }[] {
  return defaultPlannerForm().targets.map((t) => ({ r: t.value, pct: t.pct }));
}

export function emptyChartDraft(): ChartDraft {
  return { entry: null, stop: null, targets: defaultDraftTargets() };
}

const BLANK: ChartDraft = emptyChartDraft();

export function draftSide(entry: number, stop: number): "buy" | "sell" | null {
  if (!(entry > 0) || !(stop > 0) || entry === stop) return null;
  return stop < entry ? "buy" : "sell";
}

export function draftReady(draft: ChartDraft): boolean {
  return draftSide(draft.entry ?? 0, draft.stop ?? 0) != null;
}

/** D2: an open Position makes the dialog Attach. */
export function draftOpenMode(positionOpen: boolean): "enter" | "attach" {
  return positionOpen ? "attach" : "enter";
}

/** D1. With a Position, the click is the stop and the entry is the Position's average. */
export function applyDraftClick(
  draft: ChartDraft,
  price: number,
  positionEntry: number | null,
): ChartDraft {
  if (!(price > 0)) return draft;
  if (positionEntry != null && positionEntry > 0) {
    if (price === positionEntry) return draft;
    if (draft.stop == null) return { ...draft, entry: positionEntry, stop: price };
    return draft.entry === positionEntry ? draft : { ...draft, entry: positionEntry };
  }
  if (draft.entry == null) return { ...draft, entry: price };
  if (draft.stop == null) {
    if (price === draft.entry) return draft;
    return { ...draft, stop: price };
  }
  return draft;
}

export function draftTargetPrice(entry: number, stop: number, rMultiple: number): number | null {
  const side = draftSide(entry, stop);
  if (!side || !(rMultiple > 0)) return null;
  const unit = Math.abs(entry - stop);
  const raw = side === "buy" ? entry + rMultiple * unit : entry - rMultiple * unit;
  return raw > 0 ? raw : null;
}

/** R of a price on the winning side of entry. Null on the wrong side. */
export function draftRAt(entry: number, stop: number, price: number): string | null {
  const side = draftSide(entry, stop);
  if (!side) return null;
  const unit = Math.abs(entry - stop);
  if (!(unit > 0)) return null;
  const signed = side === "buy" ? price - entry : entry - price;
  if (!(signed > 0)) return null;
  return (signed / unit)
    .toFixed(4)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
}

export function moveDraftLine(
  draft: ChartDraft,
  id: string,
  price: number,
  positionEntry: number | null,
): ChartDraft {
  if (!(price > 0)) return draft;
  const attached = positionEntry != null && positionEntry > 0;
  const entry = attached ? positionEntry : draft.entry;
  if (id === "draft-entry") {
    if (attached || entry == null) return draft;
    if (price === draft.stop) return draft;
    return { ...draft, entry: price };
  }
  if (id === "draft-stop") {
    if (entry != null && price === entry) return draft;
    return { ...draft, entry: entry ?? draft.entry, stop: price };
  }
  const match = /^draft-t(\d+)$/.exec(id);
  if (!match || entry == null || draft.stop == null) return draft;
  const r = draftRAt(entry, draft.stop, price);
  const index = Number(match[1]);
  if (!r || !draft.targets[index]) return draft;
  return {
    ...draft,
    entry,
    targets: draft.targets.map((t, i) => (i === index ? { ...t, r } : t)),
  };
}

export function formatDraftPrice(price: number, decimals: number): string {
  return snapTick(price, decimals) ?? String(price);
}

export function draftDistancePct(entry: number, price: number): string {
  if (!(entry > 0)) return "";
  const pct = (Math.abs(price - entry) / entry) * 100;
  return `${pct.toFixed(2)}%`;
}

export function draftToForm(
  draft: ChartDraft,
  decimals: number,
  positionEntry: number | null,
): Partial<PlannerForm> | null {
  const attached = positionEntry != null && positionEntry > 0;
  const entry = attached ? positionEntry : draft.entry;
  if (entry == null || draft.stop == null) return null;
  const side = draftSide(entry, draft.stop);
  if (!side) return null;
  const targets = draft.targets.map((t) => ({
    kind: "r" as const,
    value: t.r,
    pct: t.pct,
    order: "limit" as const,
  }));
  const stop = formatDraftPrice(draft.stop, decimals);
  if (attached) return { side, stop, targets };
  return {
    side,
    entryType: "limit",
    entryPrice: formatDraftPrice(entry, decimals),
    stop,
    targets,
  };
}

export function draftNotice(
  preview: { plan: { warnings: string[] } | null; refused: { message: string } | null } | null,
): string {
  if (!preview) return "";
  const parts: string[] = [];
  if (preview.refused?.message) parts.push(preview.refused.message);
  for (const warning of preview.plan?.warnings ?? []) parts.push(warning);
  return parts.join(" ");
}

export function draftOverlays(opts: {
  draft: ChartDraft;
  decimals: number;
  positionEntry: number | null;
  size?: string | null;
  targetQty?: (string | null)[];
}): ChartOverlay[] {
  const attached = opts.positionEntry != null && opts.positionEntry > 0;
  const entry = attached ? opts.positionEntry : opts.draft.entry;
  const lines: ChartOverlay[] = [];
  const side = entry != null && opts.draft.stop != null ? draftSide(entry, opts.draft.stop) : null;
  if (!attached && opts.draft.entry != null && opts.draft.entry > 0) {
    const price = formatDraftPrice(opts.draft.entry, opts.decimals);
    lines.push({
      id: "draft-entry",
      kind: "draft",
      price: Number(price),
      color: side === "sell" ? theme.ask : side === "buy" ? theme.bid : theme.muted,
      label: ["ENTRY", price, opts.size ?? ""].filter(Boolean).join(" "),
      interactive: true,
    });
  }
  if (entry == null || opts.draft.stop == null || side == null) return lines;
  const stop = formatDraftPrice(opts.draft.stop, opts.decimals);
  lines.push({
    id: "draft-stop",
    kind: "draft",
    price: Number(stop),
    color: theme.ask,
    label: ["STOP", stop, draftDistancePct(entry, opts.draft.stop)].filter(Boolean).join(" "),
    interactive: true,
  });
  opts.draft.targets.forEach((t, i) => {
    const multiple = Number(t.r);
    const raw = draftTargetPrice(entry, opts.draft.stop!, multiple);
    if (raw == null) return;
    const price = formatDraftPrice(raw, opts.decimals);
    const qty = opts.targetQty?.[i] ?? "";
    lines.push({
      id: `draft-t${i}`,
      kind: "draft",
      price: Number(price),
      color: theme.bid,
      label: [`${t.r}R`, price, draftDistancePct(entry, raw), qty].filter(Boolean).join(" "),
      interactive: true,
    });
  });
  return lines;
}

type Snap = {
  armed: boolean;
  drafts: Record<string, ChartDraft>;
  notices: Record<string, string>;
  openSeq: number;
};

const serverSnap: Snap = { armed: false, drafts: {}, notices: {}, openSeq: 0 };
let armed = false;
let openSeq = 0;
const drafts = new Map<string, ChartDraft>();
const notices = new Map<string, string>();
const listeners = new Set<() => void>();
let snap: Snap = serverSnap;

function emit() {
  snap = {
    armed,
    drafts: Object.fromEntries(drafts),
    notices: Object.fromEntries(notices),
    openSeq,
  };
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

export function chartPlanArmed(): boolean {
  return armed;
}

export function setChartPlanArmed(next: boolean) {
  if (armed === next) return;
  armed = next;
  emit();
}

export function chartDraftFor(symbol: string): ChartDraft {
  return drafts.get(symbol) ?? BLANK;
}

export function clickChartDraft(symbol: string, price: number, positionEntry: number | null) {
  const next = applyDraftClick(drafts.get(symbol) ?? emptyChartDraft(), price, positionEntry);
  if (next === drafts.get(symbol)) return;
  drafts.set(symbol, next);
  emit();
}

export function moveChartDraft(
  symbol: string,
  id: string,
  price: string,
  positionEntry: number | null,
) {
  const n = Number(price);
  if (!Number.isFinite(n)) return;
  const cur = drafts.get(symbol) ?? emptyChartDraft();
  const next = moveDraftLine(cur, id, n, positionEntry);
  if (next === cur) return;
  drafts.set(symbol, next);
  emit();
}

export function clearChartDraft(symbol: string) {
  if (!drafts.has(symbol) && !notices.has(symbol)) return;
  drafts.delete(symbol);
  notices.delete(symbol);
  emit();
}

export function setChartDraftNotice(symbol: string, text: string) {
  if ((notices.get(symbol) ?? "") === text) return;
  if (text) notices.set(symbol, text);
  else notices.delete(symbol);
  emit();
}

export function requestChartDraftOpen() {
  openSeq += 1;
  emit();
}

export function useChartPlan() {
  const current = useSyncExternalStore(subscribe, () => snap, () => serverSnap);
  return { armed: current.armed, setArmed: setChartPlanArmed, openSeq: current.openSeq };
}

export function useChartDraft(symbol: string): ChartDraft {
  const current = useSyncExternalStore(subscribe, () => snap, () => serverSnap);
  return current.drafts[symbol] ?? BLANK;
}

export function useChartDraftNotice(symbol: string): string {
  const current = useSyncExternalStore(subscribe, () => snap, () => serverSnap);
  return current.notices[symbol] ?? "";
}
