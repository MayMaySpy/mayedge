import {
  ChaseParamsSheet,
  type ChaseParamsState,
} from "@/components/widgets/orderTicket/kinds/ChaseParamsSheet";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { algoReasonLabel } from "@/lib/algos";
import { api } from "@/lib/api";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import type { AlgoPlugin } from "./types";

export const CHASE_COI_BASE = 8_000_000_000;
export const CHASE_COI_END = 9_000_000_000;

function chaseDefaultState(): ChaseParamsState {
  return {
    displayQty: "",
    offsetBps: "4",
    chaseFloor: "",
    chaseCeiling: "",
  };
}

export const chaseIcebergPlugin: AlgoPlugin<ChaseParamsState> = {
  id: "chase-iceberg",
  label: "Chase",
  intent: "Passive clips behind the touch — chase, never cross",
  deskType: "chase-iceberg",
  coi: { base: CHASE_COI_BASE, end: CHASE_COI_END },
  defaultState: chaseDefaultState(),
  resetState: () => chaseDefaultState(),
  blockReason(state: unknown, ctx) {
    const s = state as ChaseParamsState;
    const floorNum = parseDecimal(s.chaseFloor) ?? NaN;
    const ceilNum = parseDecimal(s.chaseCeiling) ?? NaN;
    const clipNum = parseDecimal(s.displayQty) ?? 0;
    if (!(floorNum > 0) || !(ceilNum > floorNum)) return "Set floor / ceiling";
    if (ctx.minSz > 0 && ctx.sizeNum + 1e-9 < ctx.minSz) {
      return `Min ${trimQty(ctx.minSz, ctx.decimals)} ${ctx.symbol}`;
    }
    if (!(clipNum > 0) || clipNum > ctx.sizeNum + 1e-9) {
      return clipNum <= 0 ? "Enter clip size" : "Clip exceeds parent";
    }
    if (ctx.minSz > 0 && clipNum + 1e-9 < ctx.minSz) {
      return `Min ${trimQty(ctx.minSz, ctx.decimals)} ${ctx.symbol}`;
    }
    return null;
  },
  cta(side) {
    return side === "buy" ? "Chase buy" : "Chase sell";
  },
  async submit(state: unknown, ctx) {
    const s = state as ChaseParamsState;
    const clipNum = parseDecimal(s.displayQty) ?? 0;
    const clip = trimQty(clipNum, ctx.decimals);
    if (!clip) throw new Error("Enter clip size");
    const offsetNum = parseDecimal(s.offsetBps) ?? 0;
    const floor = canonicalDecimal(s.chaseFloor) ?? s.chaseFloor;
    const ceiling = canonicalDecimal(s.chaseCeiling) ?? s.chaseCeiling;
    const book = await api.algoStart("chase-iceberg", {
      market_index: ctx.market.market_index,
      side: ctx.side,
      qty: canonicalDecimal(String(ctx.sizeNum)) ?? ctx.qSize,
      display_qty: canonicalDecimal(s.displayQty) ?? clip,
      offset_bps:
        canonicalDecimal(s.offsetBps) ?? String(Number.isFinite(offsetNum) ? offsetNum : 4),
      price_floor: floor,
      price_ceiling: ceiling,
      reduce_only: ctx.reduceOnly,
    });
    const just = book.working?.[0];
    if (just?.status === "error") {
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "chase",
          status: "error",
          note: just.error || "Chase error",
          symbol: ctx.market.symbol,
        },
      };
    }
    if (just?.quote_action === "pause") {
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "chase",
          side: ctx.side,
          size: just.rest_qty ?? clip,
          symbol: ctx.market.symbol,
          status: "paused",
          note: algoReasonLabel(just.reason) || "waiting",
        },
      };
    }
    return {
      book,
      setLiveBook: true,
      notice: {
        kind: "chase",
        side: ctx.side,
        size: just?.rest_qty ?? clip,
        symbol: ctx.market.symbol,
        price: just?.rest_price ?? undefined,
        status: "active",
      },
    };
  },
  ParamsSheet: ChaseParamsSheet,
};
