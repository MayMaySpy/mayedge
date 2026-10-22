/** Idea page math. Rules: docs/idea-rules.md. No I/O. */

import type { Idea, IdeaTarget, JournalTrip } from "@/lib/api.gen";
import type { Market } from "@/lib/api";
import { defaultDraftTargets, type ChartDraft } from "@/lib/chartDraft";
import { canonicalDecimal } from "@/lib/numbers";
import { snapTick } from "@/lib/ticketAmend";

const BAND = 0.0025;
const DAY = 86_400_000;

export type IdeaSort = "entry" | "conviction" | "catalyst" | "updated" | "created" | "market";
export type IdeaStatusFilter = "open" | "watching" | "active" | "closed" | "dropped" | "all";

const IDEA_FILTERS: readonly IdeaStatusFilter[] = ["open", "watching", "active", "closed", "dropped", "all"];
const IDEA_SORTS: readonly IdeaSort[] = ["entry", "conviction", "catalyst", "updated", "created", "market"];

export function defaultIdeaSort(status: IdeaStatusFilter): IdeaSort {
  return status === "closed" || status === "dropped" ? "updated" : "entry";
}

/** `/ideas?id=&status=&sort=` plus a one-shot desk hand-off (`symbol`, `entry`, `stop`, `t`). */
export function readIdeasLocation(search = typeof window === "undefined" ? "" : window.location.search) {
  const q = new URLSearchParams(search);
  const statusRaw = q.get("status");
  const status: IdeaStatusFilter = IDEA_FILTERS.includes(statusRaw as IdeaStatusFilter)
    ? (statusRaw as IdeaStatusFilter)
    : "open";
  const sortRaw = q.get("sort");
  const sort: IdeaSort = IDEA_SORTS.includes(sortRaw as IdeaSort) ? (sortRaw as IdeaSort) : defaultIdeaSort(status);
  return {
    id: q.get("id"),
    status,
    sort,
    symbol: q.get("symbol")?.trim().toUpperCase() || null,
    entry: q.get("entry"),
    stop: q.get("stop"),
    targets: (q.get("t") ?? "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean),
  };
}

export type ZoneMarkKind = "stop" | "zone" | "last" | "target";

export type ZoneMark = {
  kind: ZoneMarkKind;
  label: string;
  price: string;
  sub: string;
  x: number;
};

export type ZoneBar = {
  marks: ZoneMark[];
  zone: { x0: number; x1: number } | null;
};

type Quote = {
  last_trade_price?: number | null;
  mark_price?: number | null;
  mid_price?: number | null;
};

/** L1. Zero and anything that is not a finite price are missing. */
export function marketLast(market: Quote | null | undefined): number | null {
  if (!market) return null;
  for (const raw of [market.last_trade_price, market.mark_price, market.mid_price]) {
    if (raw == null || !Number.isFinite(raw) || raw <= 0) continue;
    return raw;
  }
  return null;
}

export function inZone(idea: Idea, last: number | null): boolean {
  if (last == null || !(last > 0)) return false;
  const z = zoneOf(idea);
  if (!z) return false;
  if (z.low === z.high) return Math.abs(last - z.low) / z.low <= BAND;
  return last >= z.low && last <= z.high;
}

/** L2. Null without a zone or a Last. Zero inside the zone. */
export function toEntryPct(idea: Idea, last: number | null): number | null {
  if (last == null || !(last > 0)) return null;
  const z = zoneOf(idea);
  if (!z) return null;
  if (inZone(idea, last)) return 0;
  const edge = last < z.low ? z.low : z.high;
  const raw = ((edge - last) / last) * 100;
  return idea.side === "long" ? -raw : raw;
}

/** L4. Only a Watching Idea. */
export function pastStop(idea: Idea, last: number | null): boolean {
  if (idea.status !== "watching" || last == null || !idea.stop) return false;
  const stop = Number(idea.stop);
  if (!(stop > 0)) return false;
  return idea.side === "long" ? last <= stop : last >= stop;
}

/** L5. Only an Active Idea with a complete Plan. Positive is the trade's way. */
export function rNow(idea: Idea, last: number | null): number | null {
  if (idea.status !== "active" || last == null || !idea.plan_entry || !idea.r) return null;
  const entry = Number(idea.plan_entry);
  const risk = Number(idea.r);
  if (!(entry > 0) || !(risk > 0)) return null;
  const signed = idea.side === "long" ? last - entry : entry - last;
  return signed / risk;
}

/** P4. An R multiple becomes a price at the Market's decimals. */
export function priceAtR(
  entry: string,
  stop: string,
  side: Idea["side"],
  multiple: string,
  decimals: number,
): string | null {
  const e = Number(entry);
  const risk = Math.abs(e - Number(stop));
  const m = Number(multiple);
  if (!(e > 0) || !(risk > 0) || !(m > 0)) return null;
  const raw = side === "long" ? e + m * risk : e - m * risk;
  return snapTick(raw, decimals);
}

/** P4 the other way. Two decimal places, half up. */
/** Distance over R, half up to 2 decimals. `toPrecision` keeps a binary 2.125 from rounding down. */
function halfUp(n: number, places: number): string {
  const scale = 10 ** places;
  const shifted = Number((Math.abs(n) * scale).toPrecision(12));
  const rounded = Math.round(shifted) / scale;
  return (n < 0 ? -rounded : rounded).toFixed(places);
}

export function rAtPrice(entry: string, stop: string, price: string): string | null {
  const e = Number(entry);
  const risk = Math.abs(e - Number(stop));
  const p = Number(price);
  if (!(e > 0) || !(risk > 0) || !(p > 0)) return null;
  return halfUp(Math.abs(p - e) / risk, 2);
}

/** P5. Whole percents. The last unsized target takes the remainder. */
export function targetPercents(targets: IdeaTarget[]): string[] {
  if (targets.length === 0) return [];
  const stated = targets.map((t) => {
    if (!t.pct) return null;
    const n = Number(t.pct);
    return Number.isFinite(n) && n > 0 ? n : null;
  });
  if (stated.every((n) => n == null)) return evenShares(targets.length, 100);
  const used = stated.reduce<number>((sum, n) => sum + (n ?? 0), 0);
  const open = stated.filter((n) => n == null).length;
  const left = Math.max(0, 100 - used);
  const fill = open > 0 ? evenShares(open, Math.floor(left)) : [];
  let i = 0;
  return stated.map((n) => (n == null ? (fill[i++] ?? "0") : trimPct(n)));
}

/**
 * Blended R is Σ (R × %) / 100. Unallocated size counts as 0R.
 * No percents at all: an even split, which is the same average.
 */
export function blendedR(multiples: string[], pcts: (string | null)[]): number | null {
  if (multiples.length === 0) return null;
  const rs = multiples.map((r) => Number(r));
  if (rs.some((n) => !Number.isFinite(n))) return null;
  const weights = pcts.map((p) => (p == null || p === "" ? null : Number(p)));
  if (weights.every((n) => n == null || !Number.isFinite(n))) {
    return rs.reduce((s, n) => s + n, 0) / rs.length;
  }
  let sum = 0;
  rs.forEach((r, i) => {
    const w = weights[i];
    if (w != null && Number.isFinite(w)) sum += r * w;
  });
  return sum / 100;
}

export function planComplete(idea: Idea): boolean {
  return idea.plan_entry != null && idea.r != null && idea.stop != null;
}

/** D1 / P5. Null until the Plan is complete. */
export function ideaToDraft(idea: Idea, _decimals: number): ChartDraft | null {
  if (!planComplete(idea) || idea.plan_entry == null || idea.stop == null) return null;
  const entry = Number(idea.plan_entry);
  const stop = Number(idea.stop);
  if (!(entry > 0) || !(stop > 0) || entry === stop) return null;
  if (idea.targets.length === 0) return { entry, stop, targets: defaultDraftTargets() };
  const rs = idea.r_multiples ?? [];
  if (rs.length !== idea.targets.length) return null;
  const pcts = targetPercents(idea.targets);
  return {
    entry,
    stop,
    targets: rs.map((r, i) => ({ r, pct: pcts[i] ?? "0" })),
  };
}

/** D5. open time at or after creation, and before close when the Idea ended. */
export function ideaTrips(trips: JournalTrip[], idea: Idea): JournalTrip[] {
  return trips.filter((trip) => {
    if (trip.symbol.toUpperCase() !== idea.symbol.toUpperCase()) return false;
    const open = toMs(trip.open_ts);
    if (open < idea.created_at) return false;
    if (idea.closed_at != null && open >= idea.closed_at) return false;
    return true;
  });
}

export function ideaMatches(idea: Idea, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    idea.symbol.toLowerCase().includes(q) ||
    idea.thesis.toLowerCase().includes(q) ||
    idea.tags.some((tag) => tag.includes(q))
  );
}

export function statusOf(filter: IdeaStatusFilter, idea: Idea): boolean {
  if (filter === "all") return true;
  if (filter === "open") return idea.status === "watching" || idea.status === "active";
  return idea.status === filter;
}

export function countByStatus(ideas: Idea[]): Record<IdeaStatusFilter, number> {
  const counts: Record<IdeaStatusFilter, number> = {
    open: 0,
    watching: 0,
    active: 0,
    closed: 0,
    dropped: 0,
    all: ideas.length,
  };
  for (const idea of ideas) {
    counts[idea.status] += 1;
    if (idea.status === "watching" || idea.status === "active") counts.open += 1;
  }
  return counts;
}

export function sortIdeas(
  ideas: Idea[],
  markets: ReadonlyMap<string, Market>,
  key: IdeaSort,
): Idea[] {
  const rows = ideas.map((idea, index) => ({ idea, index, last: marketLast(markets.get(idea.symbol)) }));
  rows.sort((a, b) => compare(a, b, key) || a.index - b.index);
  return rows.map((row) => row.idea);
}

export function nextCatalyst(
  idea: Idea,
  now = Date.now(),
): { text: string; date: string; days: number } | null {
  const today = new Date(now).toISOString().slice(0, 10);
  const hit = idea.catalysts.find((c) => c.date != null && c.date >= today);
  if (!hit?.date) return null;
  const days = Math.round((Date.parse(`${hit.date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / DAY);
  return { text: hit.text, date: hit.date, days };
}

export function relativeAge(ts: number, now: number): string {
  const sec = Math.max(0, Math.floor((now - ts) / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr}h`;
  return `${Math.floor(hr / 24)}d`;
}

/** The price ruler. Null without a complete Plan. Marks run left to right by price. */
export function zoneBarMarks(idea: Idea, last: number | null, width: number): ZoneBar | null {
  if (!planComplete(idea) || idea.stop == null || idea.entry_low == null || idea.entry_high == null) {
    return null;
  }
  const stop = Number(idea.stop);
  const low = Number(idea.entry_low);
  const high = Number(idea.entry_high);
  const targets = idea.targets.map((t, i) => ({
    price: Number(t.price),
    text: t.price,
    r: idea.r_multiples?.[i] ?? "",
  }));
  const prices = [stop, low, high, ...targets.map((t) => t.price)];
  if (last != null) prices.push(last);
  const finite = prices.filter((n) => Number.isFinite(n) && n > 0);
  if (finite.length < 2) return null;
  const span = axis(finite);
  const x = (price: number) => ((price - span.min) / (span.max - span.min)) * width;
  const marks: ZoneMark[] = [
    { kind: "stop", label: "stop", price: idea.stop, sub: pctFrom(last, stop), x: x(stop) },
    { kind: "zone", label: "zone", price: low === high ? idea.entry_low : `${idea.entry_low} – ${idea.entry_high}`, sub: inZone(idea, last) ? "In zone" : pctFrom(last, (low + high) / 2), x: x((low + high) / 2) },
  ];
  if (last != null) {
    marks.push({ kind: "last", label: "Last", price: String(last), sub: "", x: x(last) });
  }
  targets.forEach((t, i) => {
    marks.push({
      kind: "target",
      label: `T${i + 1}`,
      price: t.text,
      sub: t.r ? `${t.r}R` : "",
      x: x(t.price),
    });
  });
  marks.sort((a, b) => a.x - b.x);
  return { marks, zone: { x0: x(low), x1: x(high) } };
}

function zoneOf(idea: Idea): { low: number; high: number } | null {
  if (!idea.entry_low || !idea.entry_high) return null;
  const low = Number(idea.entry_low);
  const high = Number(idea.entry_high);
  if (!(low > 0) || !(high > 0) || high < low) return null;
  return { low, high };
}

function axis(prices: number[]): { min: number; max: number } {
  let lo = Math.min(...prices);
  let hi = Math.max(...prices);
  if (!(hi > lo)) {
    const pad = lo * 0.06 || 1;
    return { min: lo - pad, max: hi + pad };
  }
  const pad = (hi - lo) * 0.06;
  return { min: lo - pad, max: hi + pad };
}

function pctFrom(last: number | null, price: number): string {
  if (last == null || !(last > 0) || !(price > 0)) return "";
  const pct = ((price - last) / last) * 100;
  const rounded = Math.round(pct * 10) / 10;
  if (rounded === 0) return "0%";
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)}%`;
}

function evenShares(count: number, total: number): string[] {
  if (count <= 0) return [];
  const base = Math.floor(total / count);
  const extra = total - base * count;
  return Array.from({ length: count }, (_, i) => String(i === count - 1 ? base + extra : base));
}

function trimPct(n: number): string {
  return String(Math.round(n * 100) / 100);
}

function toMs(ts: number): number {
  return ts > 1e12 ? ts : ts * 1000;
}

function compare(
  a: { idea: Idea; last: number | null },
  b: { idea: Idea; last: number | null },
  key: IdeaSort,
): number {
  if (key === "market") return a.idea.symbol.localeCompare(b.idea.symbol);
  if (key === "updated") return b.idea.updated_at - a.idea.updated_at;
  if (key === "created") return b.idea.created_at - a.idea.created_at;
  if (key === "conviction") return b.idea.conviction - a.idea.conviction;
  if (key === "catalyst") return catalystRank(a.idea) - catalystRank(b.idea);
  return entryRank(a) - entryRank(b);
}

function entryRank(row: { idea: Idea; last: number | null }): number {
  if (inZone(row.idea, row.last)) return -1;
  const pct = toEntryPct(row.idea, row.last);
  if (pct == null) return Number.POSITIVE_INFINITY;
  return Math.abs(pct);
}

function catalystRank(idea: Idea): number {
  const next = nextCatalyst(idea);
  return next == null ? Number.POSITIVE_INFINITY : next.days;
}

/** The listed symbol a typed one names, whatever its case. Null when none is listed. */
export function listedSymbol(listed: string[], typed: string): string | null {
  const want = typed.trim().toUpperCase();
  if (!want) return null;
  return listed.find((symbol) => symbol.toUpperCase() === want) ?? null;
}

export type PlanInput = {
  side: Idea["side"];
  low: string;
  high: string;
  stop: string;
  targets: { price: string; pct: string }[];
};

export type PlanIssue = { field: string; message: string };

/** The same sentences the server refuses with (docs/idea-rules.md P1–P2, P5). */
export function planIssue(input: PlanInput): PlanIssue | null {
  const lowRaw = input.low.trim();
  const highRaw = input.high.trim();
  if ((lowRaw && !highRaw) || (!lowRaw && highRaw)) {
    return { field: lowRaw ? "entry_high" : "entry_low", message: "A zone needs a low and a high." };
  }
  let low: number | null = null;
  let high: number | null = null;
  if (lowRaw && highRaw) {
    const lo = typedPrice(lowRaw);
    if (typeof lo !== "number") return { field: "entry_low", message: priceMessage(lo) };
    const hi = typedPrice(highRaw);
    if (typeof hi !== "number") return { field: "entry_high", message: priceMessage(hi) };
    if (hi < lo) return { field: "entry_high", message: "The entry runs from low to high." };
    low = lo;
    high = hi;
  }
  const stopRaw = input.stop.trim();
  let stop: number | null = null;
  if (stopRaw) {
    const parsed = typedPrice(stopRaw);
    if (typeof parsed !== "number") return { field: "stop", message: priceMessage(parsed) };
    stop = parsed;
    if (low != null && high != null) {
      if (input.side === "long" && !(stop < low)) {
        return { field: "stop", message: "A long stop sits below the entry." };
      }
      if (input.side === "short" && !(stop > high)) {
        return { field: "stop", message: "A short stop sits above the entry." };
      }
    }
  }
  if (input.targets.length > 4) return { field: "targets", message: "An Idea has at most 4 targets." };
  let pctSum = 0;
  for (let i = 0; i < input.targets.length; i++) {
    const row = input.targets[i];
    const priceRaw = row.price.trim();
    const pctRaw = row.pct.trim().replace(/%$/, "");
    if (!priceRaw && !pctRaw) continue;
    if (!priceRaw) return { field: `targets.${i}`, message: "A target needs a price." };
    if (low == null || high == null) return { field: "entry_low", message: "Set the entry before a target." };
    const px = typedPrice(priceRaw);
    if (typeof px !== "number") return { field: `targets.${i}`, message: priceMessage(px) };
    if (input.side === "long" && !(px > high)) {
      return { field: `targets.${i}`, message: "A long target sits above the entry." };
    }
    if (input.side === "short" && !(px < low)) {
      return { field: `targets.${i}`, message: "A short target sits below the entry." };
    }
    if (pctRaw) {
      const pct = typedPrice(pctRaw);
      if (typeof pct !== "number" || pct > 100) {
        return { field: `targets.${i}`, message: "A target size is a percent above 0 and at most 100." };
      }
      pctSum += pct;
    }
  }
  if (pctSum > 100) return { field: "targets", message: "Target sizes add up to 100 or less." };
  return null;
}

export type PlanReadout = {
  entry: string;
  r: string;
  rPct: string;
  multiples: string[];
  blended: string | null;
};

/** Live Plan summary. Null until the zone and the stop are valid. */
export function planReadout(input: PlanInput): PlanReadout | null {
  if (planIssue(input)) return null;
  const low = typedPrice(input.low.trim());
  const high = typedPrice(input.high.trim());
  const stop = typedPrice(input.stop.trim());
  if (typeof low !== "number" || typeof high !== "number" || typeof stop !== "number") return null;
  const entry = (low + high) / 2;
  const risk = Math.abs(entry - stop);
  if (!(risk > 0) || !(entry > 0)) return null;
  const rows = input.targets.filter((row) => row.price.trim());
  const entryText = fmtNum(entry);
  const stopText = fmtNum(stop);
  const multiples = rows.map((row) => rAtPrice(entryText, stopText, row.price.trim()) ?? "");
  const pcts = rows.map((row) => {
    const pct = row.pct.trim().replace(/%$/, "");
    return pct || null;
  });
  const blend = blendedR(multiples, pcts);
  return {
    entry: entryText,
    r: fmtNum(risk),
    rPct: ((risk / entry) * 100).toFixed(1),
    multiples,
    blended: blend == null ? null : blend.toFixed(1),
  };
}

function typedPrice(raw: string): number | "bad" | "zero" {
  const canon = canonicalDecimal(raw);
  if (canon == null || canon.startsWith("-")) return "bad";
  const n = Number(canon);
  if (!Number.isFinite(n)) return "bad";
  if (n === 0) return "zero";
  if (!(n > 0)) return "bad";
  return n;
}

function priceMessage(kind: "bad" | "zero"): string {
  return kind === "zero" ? "A price is above 0." : "Type the price.";
}

function fmtNum(n: number): string {
  const text = n.toFixed(8);
  if (!text.includes(".")) return text;
  return text.replace(/0+$/, "").replace(/\.$/, "");
}
