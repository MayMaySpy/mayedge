import {
  LadderParamsSheet,
  type LadderParamsState,
} from "@/components/widgets/orderTicket/kinds/LadderParamsSheet";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { algoReasonLabel } from "@/lib/algos";
import { api } from "@/lib/api";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import type { AlgoPlugin, AlgoSubmitContext } from "./types";

export const LADDER_COI_BASE = 9_000_000_000;
export const LADDER_COI_END = 10_000_000_000;

const MAX_WINDOW = 20;
const MIN_ORDERS = 2;
const MAX_ORDERS = 100;
const MAX_VAR_PCT = 50;

function newSeed(): number {
  return (Math.random() * 0x100000000) >>> 0;
}

function ladderDefaultState(): LadderParamsState {
  return {
    priceFrom: "",
    priceTo: "",
    orders: "20",
    window: "10",
    advanced: false,
    sizeVarPct: "0",
    priceVarPct: "0",
    sizeSkew: "even",
    seed: newSeed(),
  };
}

function varPct(raw: string): number | null {
  if (!raw) return 0;
  const n = parseDecimal(raw);
  if (n == null) return null;
  return n;
}

export const ladderPlugin: AlgoPlugin<LadderParamsState> = {
  id: "ladder",
  label: "Ladder",
  intent: "Limit orders across a range — keep N live, refill on fill",
  deskType: "ladder",
  coi: { base: LADDER_COI_BASE, end: LADDER_COI_END },
  defaultState: ladderDefaultState(),
  resetState: () => ladderDefaultState(),
  blockReason(state: unknown, ctx) {
    const s = state as LadderParamsState;
    const fromNum = parseDecimal(s.priceFrom) ?? NaN;
    const toNum = parseDecimal(s.priceTo) ?? NaN;
    const orders = parseInt(s.orders, 10);
    const window = parseInt(s.window, 10);
    if (!(fromNum > 0) || !(toNum > 0) || fromNum === toNum) return "Set from / to prices";
    if (!(orders >= MIN_ORDERS && orders <= MAX_ORDERS)) {
      return `Orders ${MIN_ORDERS}–${MAX_ORDERS}`;
    }
    if (!(window >= 1 && window <= MAX_WINDOW)) return `Live orders 1–${MAX_WINDOW}`;
    if (ctx.minSz > 0 && ctx.sizeNum + 1e-9 < ctx.minSz) {
      return `Min ${trimQty(ctx.minSz, ctx.decimals)} ${ctx.symbol}`;
    }
    let sizeVar = 0;
    if (s.advanced) {
      const size = varPct(s.sizeVarPct);
      const dist = varPct(s.priceVarPct);
      if (size == null || size < 0 || size > MAX_VAR_PCT) return `Size variance 0–${MAX_VAR_PCT}%`;
      if (dist == null || dist < 0 || dist > MAX_VAR_PCT) {
        return `Distance variance 0–${MAX_VAR_PCT}%`;
      }
      sizeVar = size;
    }
    const skewHaircut = s.advanced && s.sizeSkew !== "even" ? 0.5 : 1;
    const perMin = (ctx.sizeNum / orders) * (1 - sizeVar / 100) * skewHaircut;
    if (ctx.minSz > 0 && perMin + 1e-9 < ctx.minSz) {
      return `Each order ≥ ${trimQty(ctx.minSz, ctx.decimals)} — fewer orders or more size`;
    }
    return null;
  },
  cta(side) {
    return side === "buy" ? "Ladder buy" : "Ladder sell";
  },
  async submit(state: unknown, ctx: AlgoSubmitContext) {
    const s = state as LadderParamsState;
    const from = canonicalDecimal(s.priceFrom) ?? s.priceFrom;
    const to = canonicalDecimal(s.priceTo) ?? s.priceTo;
    const fromNum = parseDecimal(from) ?? 0;
    const toNum = parseDecimal(to) ?? 0;
    let priceFrom = from;
    let priceTo = to;
    if (ctx.side === "buy" && fromNum < toNum) {
      priceFrom = to;
      priceTo = from;
    } else if (ctx.side === "sell" && fromNum > toNum) {
      priceFrom = to;
      priceTo = from;
    }
    const sizeVar = s.advanced ? (canonicalDecimal(s.sizeVarPct) ?? s.sizeVarPct) : "0";
    const priceVar = s.advanced ? (canonicalDecimal(s.priceVarPct) ?? s.priceVarPct) : "0";
    const sizeSkew =
      s.advanced && s.sizeSkew === "low" ? "-1" : s.advanced && s.sizeSkew === "high" ? "1" : "0";
    const book = await api.algoStart("ladder", {
      market_index: ctx.market.market_index,
      side: ctx.side,
      qty: canonicalDecimal(String(ctx.sizeNum)) ?? ctx.qSize,
      price_from: priceFrom,
      price_to: priceTo,
      rungs: parseInt(s.orders, 10),
      window: parseInt(s.window, 10),
      size_var_pct: sizeVar || "0",
      price_var_pct: priceVar || "0",
      size_skew: sizeSkew,
      seed: s.seed,
      reduce_only: ctx.reduceOnly,
    });
    const just = book.working?.[0];
    if (just?.status === "error") {
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "ladder",
          status: "error",
          note: just.error || "Ladder error",
          symbol: ctx.market.symbol,
        },
      };
    }
    if (just?.quote_action === "pause") {
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "ladder",
          side: ctx.side,
          size: just.rest_qty ?? ctx.qSize,
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
        kind: "ladder",
        side: ctx.side,
        size: just?.rest_qty ?? ctx.qSize,
        symbol: ctx.market.symbol,
        price: just?.rest_price ?? undefined,
        status: "active",
      },
    };
  },
  ParamsSheet: LadderParamsSheet,
};
