import { lazy } from "react";
import type { TrailParamsState } from "@/components/widgets/orderTicket/kinds/TrailParamsSheet";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { api } from "@/lib/api";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import { defaultTrailDraft, trailActivationReached, trailBody, trailDistanceProblem } from "@/lib/trail";
import type { AlgoPlugin } from "./types";

const TrailParamsSheet = lazy(() =>
  import("@/components/widgets/orderTicket/kinds/TrailParamsSheet").then((m) => ({
    default: m.TrailParamsSheet,
  })),
);

/** Lockstep with backend `algos/trail/config.py` (ADR 0004). */
export const TRAIL_COI_BASE = 12_000_000_000;
export const TRAIL_COI_END = 13_000_000_000;

function trailDefaultState(): TrailParamsState {
  return { ...defaultTrailDraft(), expiryMin: "" };
}

/** The ticket starts a Trail Entry. Trail Stop and Trail TP start from a Position. */
export const trailPlugin: AlgoPlugin<TrailParamsState> = {
  id: "trail",
  label: "Trail",
  intent: "Enter when price comes back a set distance off its best",
  deskType: "trail",
  coi: { base: TRAIL_COI_BASE, end: TRAIL_COI_END },
  defaultState: trailDefaultState(),
  resetState: () => trailDefaultState(),
  blockReason(state: unknown, ctx) {
    const s = state as TrailParamsState;
    if (ctx.reduceOnly) return "Trail exits start from the Position";
    const spot = ctx.spot ?? 0;
    const problem = trailDistanceProblem(s, spot, ctx.priceDecimals ?? 8);
    if (problem) return problem;
    if (ctx.minSz > 0 && ctx.sizeNum + 1e-9 < ctx.minSz) {
      return `Min ${trimQty(ctx.minSz, ctx.decimals)} ${ctx.symbol}`;
    }
    return null;
  },
  cta(side) {
    return side === "buy" ? "Trail buy" : "Trail sell";
  },
  async submit(state: unknown, ctx) {
    const s = state as TrailParamsState;
    const act = parseDecimal(s.activation);
    const spot = ctx.spot ?? 0;
    if (act != null && act > 0 && spot > 0 && trailActivationReached(ctx.side, spot, act)) {
      throw new Error(
        ctx.side === "buy" ? "Activate at must be below mark" : "Activate at must be above mark"
      );
    }
    const book = await api.algoStart(
      "trail",
      trailBody(s, {
        kind: "entry",
        market_index: ctx.market.market_index,
        side: ctx.side,
        size: canonicalDecimal(String(ctx.sizeNum)) ?? ctx.qSize,
        expiry_min: s.expiryMin ? Number(s.expiryMin) : null,
        slippage: ctx.slipFrac,
      })
    );
    return {
      book,
      setLiveBook: true,
      notice: {
        kind: "trail",
        title: "Trail Entry started",
        side: ctx.side,
        size: ctx.qSize,
        symbol: ctx.market.symbol,
      },
    };
  },
  ParamsSheet: TrailParamsSheet,
};

