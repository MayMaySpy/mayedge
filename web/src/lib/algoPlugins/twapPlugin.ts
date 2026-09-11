import {
  TwapParamsSheet,
  type TwapParamsState,
} from "@/components/widgets/orderTicket/kinds/TwapParamsSheet";
import {
  twapDurationSeconds,
  twapFreqSeconds,
  twapSlipFromMaxPrice,
} from "@/lib/algos";
import { api } from "@/lib/api";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import type { AlgoPlugin } from "./types";

export const TWAP_COI_BASE = 7_000_000_000;
export const TWAP_COI_END = 8_000_000_000;

function twapDefaultState(): TwapParamsState {
  return {
    twapHours: "",
    twapMinutes: "30",
    twapMaxPrice: "",
    twapAdvanced: false,
    twapRandomize: true,
    twapStyle: "neutral",
    twapFreq: "5",
    twapIndexPct: "",
  };
}

export const twapPlugin: AlgoPlugin<TwapParamsState> = {
  id: "twap",
  label: "TWAP",
  intent: "Time-weighted slices over the running time",
  deskType: "advanced-twap",
  coi: { base: TWAP_COI_BASE, end: TWAP_COI_END },
  defaultState: twapDefaultState(),
  resetState: () => twapDefaultState(),
  blockReason(state: unknown, ctx) {
    const s = state as TwapParamsState;
    const twapSec = twapDurationSeconds(s.twapHours, s.twapMinutes);
    if (twapSec == null) return "Running time 1m–30d";
    if (s.twapAdvanced) {
      const freq = twapFreqSeconds(s.twapFreq);
      if (freq == null || freq < 2 || freq > 3600) return "Slice 2s–1h";
      return null;
    }
    const twapSlip =
      twapSlipFromMaxPrice(parseDecimal(s.twapMaxPrice) ?? 0, ctx.spot ?? 0) ??
      (ctx.slipFrac ?? 0);
    if (parseDecimal(s.twapMaxPrice) != null && twapSlip > 0.05 + 1e-9) {
      return "Max 5% from mark";
    }
    return null;
  },
  cta(side) {
    return side === "buy" ? "TWAP buy" : "TWAP sell";
  },
  async submit(state: unknown, ctx) {
    const s = state as TwapParamsState;
    const twapSec = twapDurationSeconds(s.twapHours, s.twapMinutes);
    if (twapSec == null) throw new Error("Running time 1m–30d");
    if (s.twapAdvanced) {
      const freq = twapFreqSeconds(s.twapFreq);
      if (freq == null) throw new Error("Slice 2s–1h");
      const book = await api.algoStart("advanced-twap", {
        market_index: ctx.market.market_index,
        side: ctx.side,
        qty: canonicalDecimal(String(ctx.sizeNum)) ?? ctx.qSize,
        duration_seconds: twapSec,
        frequency_seconds: freq,
        style: s.twapStyle,
        randomize: s.twapRandomize,
        max_price: parseDecimal(s.twapMaxPrice) != null ? canonicalDecimal(s.twapMaxPrice) : null,
        max_index_pct:
          parseDecimal(s.twapIndexPct) != null ? canonicalDecimal(s.twapIndexPct) : null,
        reduce_only: ctx.reduceOnly,
      });
      return {
        book,
        setLiveBook: true,
        notice: {
          kind: "twap",
          status: "active",
          side: ctx.side,
          size: ctx.qSize,
          symbol: ctx.market.symbol,
        },
      };
    }
    await api.placeTwapOrder({
      market_index: ctx.market.market_index,
      side: ctx.side,
      size: ctx.qSize,
      duration_seconds: twapSec,
      max_slippage:
        twapSlipFromMaxPrice(parseDecimal(s.twapMaxPrice) ?? 0, ctx.spot ?? 0) ??
        (ctx.slipFrac || 0.01),
      reduce_only: ctx.reduceOnly,
    });
    return {
      notice: {
        kind: "twap",
        side: ctx.side,
        size: ctx.qSize,
        symbol: ctx.market.symbol,
      },
    };
  },
  ParamsSheet: TwapParamsSheet,
};
