import {
  GridParamsSheet,
  type GridParamsState,
} from "@/components/widgets/orderTicket/kinds/GridParamsSheet";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { algoReasonLabel } from "@/lib/algos";
import { api } from "@/lib/api";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import type { AlgoPlugin } from "./types";

export const GRID_COI_BASE = 10_000_000_000;
export const GRID_COI_END = 11_000_000_000;

function gridDefaultState(): GridParamsState {
  return {
    displayQty: "",
    offsetBps: "4",
    profitBps: "40",
    gridBps: "40",
    gridLinked: true,
    chaseFloor: "",
    chaseCeiling: "",
    beDelayMs: "120000",
  };
}

export const chaseGridPlugin: AlgoPlugin<GridParamsState> = {
  id: "chase-grid",
  label: "Grid",
  intent: "Chase the open side; profit orders close — merge, optional B/E",
  deskType: "chase-grid",
  coi: { base: GRID_COI_BASE, end: GRID_COI_END },
  defaultState: gridDefaultState(),
  resetState: () => gridDefaultState(),
  blockReason(state: unknown, ctx) {
    const s = state as GridParamsState;
    const floorNum = parseDecimal(s.chaseFloor) ?? NaN;
    const ceilNum = parseDecimal(s.chaseCeiling) ?? NaN;
    const clipNum = parseDecimal(s.displayQty) ?? 0;
    const profitNum = parseDecimal(s.profitBps) ?? 0;
    const gridNum = parseDecimal(s.gridBps) ?? 0;
    if (!(floorNum > 0) || !(ceilNum > floorNum)) return "Set floor / ceiling";
    if (!(profitNum > 0)) return "Enter profit (bp)";
    if (!(gridNum > 0)) return "Enter grid step (bp)";
    if (ctx.minSz > 0 && ctx.sizeNum + 1e-9 < ctx.minSz) {
      return `Min ${trimQty(ctx.minSz, ctx.decimals)} ${ctx.symbol}`;
    }
    if (!(clipNum > 0)) return "Enter clip size";
    if (ctx.minSz > 0 && clipNum + 1e-9 < ctx.minSz) {
      return `Min ${trimQty(ctx.minSz, ctx.decimals)} ${ctx.symbol}`;
    }
    return null;
  },
  cta() {
    return "Start grid";
  },
  singleAction: true,
  async submit(state: unknown, ctx) {
    const s = state as GridParamsState;
    const clipNum = parseDecimal(s.displayQty) ?? 0;
    const clip = trimQty(clipNum, ctx.decimals);
    if (!clip) throw new Error("Enter clip size");
    const floor = canonicalDecimal(s.chaseFloor) ?? s.chaseFloor;
    const ceiling = canonicalDecimal(s.chaseCeiling) ?? s.chaseCeiling;
    const book = await api.algoStart("chase-grid", {
      market_index: ctx.market.market_index,
      qty: canonicalDecimal(String(ctx.sizeNum)) ?? ctx.qSize,
      display_qty: canonicalDecimal(s.displayQty) ?? clip,
      offset_bps: canonicalDecimal(s.offsetBps) ?? "4",
      profit_bps: canonicalDecimal(s.profitBps) ?? s.profitBps,
      grid_bps: canonicalDecimal(s.gridBps) ?? s.gridBps,
      price_floor: floor,
      price_ceiling: ceiling,
      be_delay_ms: parseInt(s.beDelayMs, 10) || 0,
    });
    const just = book.working?.[0];
    if (just?.status === "error") {
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "grid",
          status: "error",
          note: just.error || "Grid error",
          symbol: ctx.market.symbol,
        },
      };
    }
    if (just?.quote_action === "pause") {
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "grid",
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
        kind: "grid",
        size: just?.rest_qty ?? clip,
        symbol: ctx.market.symbol,
        price: just?.rest_price ?? undefined,
        status: "active",
      },
    };
  },
  ParamsSheet: GridParamsSheet,
};
