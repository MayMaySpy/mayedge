import type {
  AlgoBook,
  AlgoState,
  OpenOrder,
  TrailDistanceKind,
  TrailKind,
  TrailReference,
} from "@/lib/api";
import { algoIsWorking } from "@/lib/algos";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";

/** Trail's form math and words. Rules live in docs/trail-rules.md; the desk has the last word. */

export const TRAIL_KIND_LABEL: Record<TrailKind, string> = {
  entry: "Trail Entry",
  stop: "Trail Stop",
  tp: "Trail TP",
};

export interface TrailDraft {
  distance: string;
  distanceKind: TrailDistanceKind;
  reference: TrailReference;
  activation: string;
}

export function defaultTrailDraft(): TrailDraft {
  return { distance: "1", distanceKind: "pct", reference: "mark", activation: "" };
}

/** +1 when the best price is the highest (a sell fires on a fall), −1 when the lowest. */
export function trailFavour(side: "buy" | "sell"): 1 | -1 {
  return side === "sell" ? 1 : -1;
}

export function trailOffset(draft: Pick<TrailDraft, "distance" | "distanceKind">, best: number): number {
  const d = parseDecimal(draft.distance) ?? NaN;
  if (!(d > 0) || !(best > 0)) return NaN;
  return draft.distanceKind === "pct" ? (best * d) / 100 : d;
}

/** F2 and F3: the distance behind the best price, rounded to the tick away from it. */
export function trailTriggerAt(
  side: "buy" | "sell",
  draft: Pick<TrailDraft, "distance" | "distanceKind">,
  best: number,
  priceDecimals: number
): number {
  const off = trailOffset(draft, best);
  if (!Number.isFinite(off)) return NaN;
  const raw = best - trailFavour(side) * off;
  const scale = 10 ** priceDecimals;
  const n = raw * scale;
  // A tiny nudge so 2.21625 × 1e4 does not land at 22162.499….
  const rounded = side === "sell" ? Math.floor(n + 1e-7) : Math.ceil(n - 1e-7);
  return rounded / scale;
}

/** S3: under 2 ticks at today's price refuses. Null when it is fine. */
export function trailDistanceProblem(
  draft: Pick<TrailDraft, "distance" | "distanceKind">,
  mark: number,
  priceDecimals: number
): string | null {
  const d = parseDecimal(draft.distance) ?? NaN;
  if (!(d > 0)) return "Set a distance";
  if (draft.distanceKind === "pct" && d >= 100) return "Distance must be under 100%";
  const at = trailOffset(draft, mark);
  const tick = 10 ** -priceDecimals;
  if (mark > 0 && at < tick * 2 - 1e-12) return "Distance is under 2 ticks";
  return null;
}

/** F5: has price reached the Activation on the favourable side? */
export function trailActivationReached(side: "buy" | "sell", price: number, activation: number): boolean {
  return trailFavour(side) * (price - activation) >= 0;
}

export function trailDistanceLabel(distance: string | null | undefined, kind: TrailDistanceKind | null | undefined): string {
  if (!distance) return "—";
  return kind === "pct" ? `${distance}%` : distance;
}

export function trailReferenceLabel(ref: TrailReference | null | undefined): string {
  return ref === "last" ? "Last" : "Mark";
}

/** The body the desk's /algos/trail/start takes, from a draft. */
export function trailBody(
  draft: TrailDraft,
  extra: Record<string, unknown>
): Record<string, unknown> {
  return {
    distance: canonicalDecimal(draft.distance) ?? draft.distance,
    distance_kind: draft.distanceKind,
    reference: draft.reference,
    activation: canonicalDecimal(draft.activation) ?? null,
    ...extra,
  };
}

export type TrailPhase = "waiting" | "following" | "firing" | "not following" | "paused" | "error";

export function trailPhase(algo: AlgoState): TrailPhase {
  const rt = algo.trail;
  if (algo.status === "error") return "error";
  if (algo.status === "paused") return "paused";
  if (!rt) return "waiting";
  if (!rt.following) return "not following";
  if (rt.fired_at) return "firing";
  return rt.active ? "following" : "waiting";
}

export function liveTrailsFor(
  book: AlgoBook | null | undefined,
  marketIndex: number | null | undefined
): AlgoState[] {
  if (!book || marketIndex == null) return [];
  return (book.working ?? []).filter(
    (a) => a.algo_type === "trail" && a.market_index === marketIndex && algoIsWorking(a.status)
  );
}

export function liveTrailStop(
  book: AlgoBook | null | undefined,
  marketIndex: number | null | undefined
): AlgoState | null {
  return liveTrailsFor(book, marketIndex).find((a) => a.trail?.kind === "stop") ?? null;
}

/** TS4: the Stop Tickets a Trail Stop takes over. Algo orders are never a Ticket. */
export function stopTicketsReplaced(
  orders: OpenOrder[],
  marketIndex: number,
  closeSide: "buy" | "sell",
  isAlgo: (coi: string | number | null | undefined) => boolean,
  isStop: (orderType: string) => boolean
): OpenOrder[] {
  return orders.filter(
    (o) =>
      o.market_index === marketIndex &&
      isStop(o.order_type) &&
      !isAlgo(o.client_order_index) &&
      (!o.side || o.side === closeSide)
  );
}

/** A Trail Stop or Trail Take Profit drafted in the Position editor. */
export interface TrailExitDraft extends TrailDraft {
  /** A Stop's start price. Empty means mark − distance. */
  start: string;
}

export function defaultTrailExitDraft(): TrailExitDraft {
  return { distance: "1", distanceKind: "pct", reference: "mark", activation: "", start: "" };
}

/** What is wrong with a Trail exit draft, or null (trail-rules S3, TT1). */
export function trailExitProblem(
  kind: "stop" | "tp",
  draft: TrailExitDraft,
  closeSide: "buy" | "sell",
  mark: number,
  liq: number,
  priceDecimals: number
): string | null {
  const dist = trailDistanceProblem(draft, mark, priceDecimals);
  if (dist) return dist;
  const act = parseDecimal(draft.activation);
  if (kind === "tp" && !(act != null && act > 0)) return "Set Activate at";
  if (act != null && act > 0 && trailActivationReached(closeSide, mark, act)) {
    return closeSide === "sell" ? "Activate at must be above mark" : "Activate at must be below mark";
  }
  if (kind === "stop") {
    const start = parseDecimal(draft.start);
    if (start != null && start > 0) {
      const ok = closeSide === "sell" ? start < mark : start > mark;
      if (!ok) return closeSide === "sell" ? "Start must be below mark" : "Start must be above mark";
      if (liq > 0 && (closeSide === "sell" ? start <= liq : start >= liq)) {
        return "Start is beyond the Liquidation price";
      }
    }
  }
  return null;
}

