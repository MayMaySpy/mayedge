import { MassagerParamsSheet } from "@/components/widgets/orderTicket/kinds/MassagerParamsSheet";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { api } from "@/lib/api";
import { massagerInput, massagerRefusal, type MassagerParamsState } from "@/lib/massager";
import { canonicalDecimal } from "@/lib/numbers";
import { startNotice } from "./startNotice";
import type { AlgoPlugin } from "./types";

/** Lockstep with backend `algos/massager/config.py` (ADR 0004). */
export const MASSAGER_COI_BASE = 13_000_000_000;
export const MASSAGER_COI_END = 14_000_000_000;

function massagerDefaultState(): MassagerParamsState {
  return {
    stepMode: "fixed",
    step: "",
    atrMult: "0.5",
    atrTf: "1h",
    atrStep: "",
    chaseFloor: "",
    chaseCeiling: "",
  };
}

export const massagerPlugin: AlgoPlugin<MassagerParamsState> = {
  id: "massager",
  label: "Massager",
  intent: "Work an open Position up and down inside a Band, back to its Core",
  deskType: "massager",
  coi: { base: MASSAGER_COI_BASE, end: MASSAGER_COI_END },
  defaultState: massagerDefaultState(),
  resetState: () => massagerDefaultState(),
  blockReason(state: unknown, ctx) {
    const s = state as MassagerParamsState;
    if (ctx.reduceOnly) return "A Massager is never reduce-only";
    if (!(ctx.sizeNum > 0)) return "Enter the Swing as size";
    // MS6 needs the account's fee; the backend checks it at Start.
    return massagerRefusal(
      massagerInput(s, {
        market: { price_decimals: ctx.priceDecimals ?? 4, size_decimals: ctx.decimals },
        swing: ctx.sizeNum,
        position: ctx.signedPos ?? 0,
        mid: ctx.spot ?? null,
        minQty: ctx.minBase ?? 0,
        makerBps: 0,
      })
    );
  },
  cta() {
    return "Start Massager";
  },
  singleAction: true,
  sizeLabel: "Swing",
  async submit(state: unknown, ctx) {
    const s = state as MassagerParamsState;
    const swing = trimQty(ctx.sizeNum, ctx.decimals);
    if (!swing) throw new Error("Enter the Swing as size");
    const book = await api.algoStart("massager", {
      market_index: ctx.market.market_index,
      band_low: canonicalDecimal(s.chaseFloor) ?? s.chaseFloor,
      band_high: canonicalDecimal(s.chaseCeiling) ?? s.chaseCeiling,
      swing: canonicalDecimal(swing) ?? swing,
      ...(s.stepMode === "atr"
        ? {
            step_mode: "atr",
            atr_mult: canonicalDecimal(s.atrMult) ?? s.atrMult,
            atr_tf: s.atrTf,
          }
        : { step: canonicalDecimal(s.step) ?? s.step }),
    });
    return startNotice(book, ctx, { kind: "massager", label: "Massager", size: swing });
  },
  ParamsSheet: MassagerParamsSheet,
};
