import type { ComponentType } from "react";
import type { Market, AlgoBook } from "@/lib/api";
import type { OrderNoticeInput } from "@/lib/orderNotice";

export interface AlgoCoiBand {
  base: number;
  end: number;
}

export interface AlgoBlockContext {
  sizeNum: number;
  decimals: number;
  minSz: number;
  symbol: string;
  maxSize?: number;
  spot?: number | null;
  slipFrac?: number;
}

export interface AlgoSubmitContext {
  market: Market;
  side: "buy" | "sell";
  qSize: string;
  sizeNum: number;
  decimals: number;
  reduceOnly: boolean;
  spot: number | null;
  slipFrac: number;
}

export interface AlgoParamsSheetProps<TState> {
  market: Market;
  bookMid: number | null;
  sizeNum: number;
  state: TState;
  onStateChange: (state: TState) => void;
}

export interface AlgoPlugin<TState = unknown> {
  id: string;
  label: string;
  intent: string;
  /** Backend `algo_type` for desk-managed starts. Omit for venue-only algos. */
  deskType?: string;
  coi: AlgoCoiBand | null;
  defaultState: TState;
  resetState: (prev: unknown) => TState;
  blockReason: (state: unknown, ctx: AlgoBlockContext) => string | null;
  cta: (side: "buy" | "sell") => string;
  submit: (
    state: unknown,
    ctx: AlgoSubmitContext
  ) => Promise<{ book?: AlgoBook; notice: OrderNoticeInput; setLiveBook?: boolean }>;
  ParamsSheet: ComponentType<AlgoParamsSheetProps<TState>>;
}

export function coiInBand(coi: string | number | null | undefined, band: AlgoCoiBand): boolean {
  if (coi == null || coi === "") return false;
  const n = typeof coi === "number" ? coi : Number(coi);
  return Number.isFinite(n) && n >= band.base && n < band.end;
}
