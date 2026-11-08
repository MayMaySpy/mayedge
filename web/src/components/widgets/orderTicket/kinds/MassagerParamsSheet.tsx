import { useEffect, useState } from "react";
import { FieldGroup } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import { useLiveAccount, useLiveAlgos } from "@/lib/liveData";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import {
  atrMultLabel,
  chopLabelText,
  chopReading,
  closedAtr,
  MASSAGER_ATR_MULTIPLES,
  massagerInput,
  massagerPreview,
  massagerRefusal,
  runningMassager,
  type MassagerAtrTf,
  type MassagerCarry,
  type MassagerChop,
  type MassagerChopLabel,
  type MassagerParamsState,
} from "@/lib/massager";
import { marketPrice } from "@/lib/marketFormat";
import { cn, formatPrice, formatSize, formatUsd } from "@/lib/utils";
import { chaseBandFromPct } from "../math";
import { TicketChips, TicketField } from "../ui";

const TF_NEXT: Record<MassagerAtrTf, MassagerAtrTf> = { "15m": "1h", "1h": "4h", "4h": "15m" };
const CHOP_TONE: Record<MassagerChopLabel, string> = {
  ranging: "text-bid",
  mixed: "text-muted-foreground",
  trending: "text-ask",
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 justify-between gap-2">
      <span className="shrink-0">{label}</span>
      <span className="truncate text-right text-text">{children}</span>
    </div>
  );
}

export function MassagerParamsSheet({
  market,
  bookMid,
  sizeNum,
  state,
  onStateChange,
}: AlgoParamsSheetProps<MassagerParamsState>) {
  const set = (patch: Partial<MassagerParamsState>) => onStateChange({ ...state, ...patch });
  const account = useLiveAccount();
  const algos = useLiveAlgos();
  const sym = market.symbol;
  const running = runningMassager(algos.working, sym);
  const position =
    parseFloat(
      account?.positions.find((p) => p.market_index === market.market_index)?.size ?? "0"
    ) || 0;
  const makerBps = parseDecimal(account?.maker_fee_bps ?? "0") ?? 0;
  const input = massagerInput(state, {
    market,
    swing: sizeNum,
    position,
    mid: bookMid,
    minQty: market.min_base_amount ?? 0,
    makerBps,
  });
  const preview = massagerPreview(input);
  const refusal = massagerRefusal(input);
  const atr = useClosedAtr(sym, state.atrTf);
  const priceDecimals = market.price_decimals ?? 4;
  const follow = state.stepMode === "atr";
  const k = parseDecimal(state.atrMult) ?? 0;
  // MS19: a following Step is k × the ATR now; keep it in the state so Start can be checked.
  const atrStep = follow && atr != null && k > 0 ? formatPrice(atr * k, priceDecimals) : "";
  useEffect(() => {
    if (follow && state.atrStep !== atrStep) onStateChange({ ...state, atrStep });
  }, [follow, atrStep, state, onStateChange]);
  // MS24: the Chop reading, kept in the state so Start sends it.
  const chop = useChop(sym, bookMid, input.tick);
  useEffect(() => {
    if (!sameChop(state.chop, chop)) onStateChange({ ...state, chop });
  }, [chop, state, onStateChange]);
  const carry = useCarry(market.market_index, running ? 0 : position);

  if (running) {
    return (
      <p className="text-sm leading-snug text-muted-foreground">
        {running.algo_id ?? "A Massager"} already works {sym}. Stop it in Algos to start a new
        run at new levels; its Basis carries.
      </p>
    );
  }

  const atrLabel = atr == null ? "ATR loading" : `ATR ${state.atrTf} ${marketPrice(atr, sym)}`;
  const tfButton = (
    <button
      type="button"
      className="font-mono text-sm text-muted-foreground hover:text-text"
      onClick={() => set({ atrTf: TF_NEXT[state.atrTf] })}
      title={`${atrLabel}. Click for 15m, 1h or 4h candles`}
    >
      {state.atrTf}
    </button>
  );
  const range = chop?.bandLow != null && chop.bandHigh != null ? chop : null;
  const fillRange = () => {
    if (range == null) return;
    set({
      chaseFloor: formatPrice(range.bandLow!, priceDecimals),
      chaseCeiling: formatPrice(range.bandHigh!, priceDecimals),
    });
  };
  const carries = carry?.carried === true && !state.fresh;

  return (
    <FieldGroup className="gap-2">
      <FieldGroup className="grid grid-cols-2 gap-2">
        <TicketField
          id="massager-floor"
          label="Floor"
          value={state.chaseFloor}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => set({ chaseFloor: v })}
        />
        <TicketField
          id="massager-ceil"
          label="Ceiling"
          value={state.chaseCeiling}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => set({ chaseCeiling: v })}
        />
      </FieldGroup>
      <TicketChips
        label="Band"
        sticky={false}
        ariaLabel="Band"
        onValueChange={(v) => {
          if (v === "24h") return fillRange();
          const band = chaseBandFromPct(market, parseFloat(v), bookMid);
          set({ chaseFloor: band.floor, chaseCeiling: band.ceiling });
        }}
        items={[
          {
            value: "24h",
            label: "24h",
            disabled: range == null,
            title: range
              ? `${marketPrice(range.bandLow, sym)} to ${marketPrice(range.bandHigh, sym)}: the last 24 closed 1h candles`
              : "Price is outside the last 24h range",
          },
          { value: "1", label: "±1%" },
          { value: "2", label: "±2%" },
        ]}
        trailing={
          chop && (
            <span
              className={cn("shrink-0 font-mono text-sm", CHOP_TONE[chop.label])}
              title={`Chop ${chop.er.toFixed(2)}: efficiency of the last 24 closed 1h candles. Under 0.3 ranges, 0.5 and up trends.`}
            >
              {chopLabelText(chop.label)}
            </span>
          )
        }
      />
      {follow ? (
        <TicketField
          id="massager-atr-mult"
          label="Step × ATR"
          value={state.atrMult}
          inputMode="decimal"
          placeholder="0.5"
          sanitize={decimalInput}
          onChange={(v) => set({ atrMult: v })}
          addon={tfButton}
        />
      ) : (
        <TicketField
          id="massager-step"
          label="Step"
          value={state.step}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => set({ step: v })}
          addon={tfButton}
        />
      )}
      <TicketChips
        label="ATR"
        sticky={follow}
        value={follow ? state.atrMult : undefined}
        ariaLabel="Step from ATR"
        onValueChange={(v) => {
          if (follow) return set({ atrMult: v });
          const m = parseFloat(v);
          if (atr == null || !Number.isFinite(m)) return;
          set({ step: formatPrice(atr * m, priceDecimals) });
        }}
        items={MASSAGER_ATR_MULTIPLES.map((m) => ({
          value: String(m),
          label: `${atrMultLabel(m)}×`,
          disabled: !follow && atr == null,
          title:
            atr == null
              ? "ATR loading"
              : `${formatPrice(atr * m, priceDecimals)}: ${m} × ${atrLabel}`,
        }))}
        trailing={<FollowSwitch on={follow} onChange={(on) => set({ stepMode: on ? "atr" : "fixed" })} />}
      />
      {position !== 0 && sizeNum > 0 && refusal ? (
        <p className="text-sm leading-snug text-ask">{refusal}</p>
      ) : preview ? (
        <div
          className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-sm text-muted-foreground"
          title="Sells above the Center and buys back below, two levels each side, post-only. A 1h close outside the Band pauses it and pushes."
        >
          <Fact label="Clip">
            {formatSize(preview.clip)} × {preview.levels}
          </Fact>
          <Fact label="Per trip">{formatUsd(preview.perRoundTrip)}</Fact>
          <Fact label="Position">
            {formatSize(preview.positionLow)}–{formatSize(preview.positionHigh)}
          </Fact>
          <Fact label="At an edge">
            <span
              className="text-ask"
              title="Against holding the Core, with price at a Band end and every level on that side filled. Past the end it costs the Swing times the further move."
            >
              −{formatUsd(preview.edgeCost)}
            </span>
          </Fact>
          <Fact label="Catch-up">
            {preview.catchUp.side ? `${preview.catchUp.side} ${formatSize(preview.catchUp.qty)}` : "none"}
          </Fact>
          {follow && <Fact label="Step">{atrStep ? marketPrice(atrStep, sym) : "…"}</Fact>}
          {preview.swing < sizeNum - 1e-9 && <Fact label="Swing">{formatSize(preview.swing)}</Fact>}
          {preview.fewLevels && (
            <p className="col-span-2 font-sans leading-snug">
              {preview.levels} {preview.levels === 1 ? "level" : "levels"} a side: fills come few and
              lumpy. A smaller Step gives more for the same Swing.
            </p>
          )}
          {carry && (
            <div className="col-span-2 flex min-w-0 items-center justify-between gap-2">
              <span className="truncate" title={carries ? undefined : carry.why}>
                Basis{" "}
                <span className="text-text">
                  {carries
                    ? `${marketPrice(carry.basis, sym)} from ${carry.source ?? "the last run"}, run ${carry.runs ?? 1}`
                    : "starts new"}
                </span>
              </span>
              {carry.carried && (
                <button
                  type="button"
                  className="shrink-0 text-muted-foreground underline-offset-2 hover:text-text hover:underline"
                  onClick={() => set({ fresh: !state.fresh })}
                  title={
                    state.fresh
                      ? `Carry ${carry.source}'s Basis and Captured`
                      : "Start a new Tally: Basis from the entry, Captured from 0"
                  }
                >
                  {state.fresh ? "carry" : "start new"}
                </button>
              )}
            </div>
          )}
        </div>
      ) : account != null && position === 0 ? (
        <p className="text-sm text-muted-foreground">A Massager needs an open Position on {sym}.</p>
      ) : null}
    </FieldGroup>
  );
}

function FollowSwitch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <label
      className="flex shrink-0 cursor-pointer items-center gap-1.5 text-sm text-muted-foreground"
      title="Follow ATR: the Step re-reads k × ATR after each candle and moves the levels when 20% off"
    >
      Follow
      <Switch checked={on} onCheckedChange={(v) => onChange(v === true)} aria-label="Step follows ATR" />
    </label>
  );
}

/** MS19, MS21: ATR(14) on the closed candles of a timeframe. Null until loaded. */
function useClosedAtr(symbol: string, timeframe: MassagerAtrTf): number | null {
  const key = `${symbol}:${timeframe}`;
  const [atr, setAtr] = useState<{ key: string; value: number | null } | null>(null);
  useEffect(() => {
    let live = true;
    api
      .candles(symbol, timeframe, 100)
      .then((candles) => {
        if (live) setAtr({ key, value: closedAtr(candles, timeframe, Date.now()) });
      })
      .catch(() => {
        if (live) setAtr({ key, value: null });
      });
    return () => {
      live = false;
    };
  }, [key, symbol, timeframe]);
  return atr?.key === key ? atr.value : null;
}

function sameChop(a: MassagerChop | null, b: MassagerChop | null): boolean {
  if (a == null || b == null) return a === b;
  return a.er === b.er && a.label === b.label && a.bandLow === b.bandLow && a.bandHigh === b.bandHigh;
}

/** MS24: the Chop reading on the last 24 closed 1h candles. Null until loaded. */
function useChop(symbol: string, mid: number | null, tick: number): MassagerChop | null {
  const [candles, setCandles] = useState<{
    symbol: string;
    at: number;
    rows: Awaited<ReturnType<typeof api.candles>>;
  } | null>(null);
  useEffect(() => {
    let live = true;
    api
      .candles(symbol, "1h", 48)
      .then((rows) => {
        if (live) setCandles({ symbol, at: Date.now(), rows });
      })
      .catch(() => {
        if (live) setCandles({ symbol, at: Date.now(), rows: [] });
      });
    return () => {
      live = false;
    };
  }, [symbol]);
  if (candles?.symbol !== symbol) return null;
  return chopReading(candles.rows, { nowMs: candles.at, mid, tick });
}

/** MS19, MS22: the Tally a Start would carry, asked again when the Position changes. */
function useCarry(marketIndex: number, position: number): MassagerCarry | null {
  const key = `${marketIndex}:${position}`;
  const [carry, setCarry] = useState<{ key: string; value: MassagerCarry | null } | null>(null);
  useEffect(() => {
    let live = true;
    if (position === 0) return;
    api
      .massagerCarry(marketIndex)
      .then((value) => {
        if (live) setCarry({ key, value });
      })
      .catch(() => {
        if (live) setCarry({ key, value: null });
      });
    return () => {
      live = false;
    };
  }, [key, marketIndex, position]);
  return carry?.key === key ? carry.value : null;
}
