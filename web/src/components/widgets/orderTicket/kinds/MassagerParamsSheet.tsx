import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import { api } from "@/lib/api";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import { useLiveAccount } from "@/lib/liveData";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import {
  atrMultLabel,
  chopLabelText,
  chopReading,
  closedAtr,
  MASSAGER_ATR_MULTIPLES,
  MASSAGER_ATR_TIMEFRAMES,
  massagerInput,
  massagerPreview,
  massagerRefusal,
  type MassagerAtrTf,
  type MassagerCarry,
  type MassagerChop,
  type MassagerParamsState,
} from "@/lib/massager";
import { marketPrice } from "@/lib/marketFormat";
import { formatPrice, formatSigned, formatSize, formatUsd } from "@/lib/utils";
import { TicketChips, TicketField, ToggleRow } from "../ui";
import { BandFields } from "./ChaseFields";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span>
      {label} <span className="text-text">{children}</span>
    </span>
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
  const refusal = position === 0 ? massagerRefusal(input) : null;
  const sym = market.symbol;
  const atr = useClosedAtr(sym, state.atrTf);
  const priceDecimals = market.price_decimals ?? 4;
  const atrMode = state.stepMode === "atr";
  const k = parseDecimal(state.atrMult) ?? 0;
  // MS19: an ATR Step is k × the ATR now; keep it in the state so Start can be checked.
  const atrStep = atrMode && atr != null && k > 0 ? formatPrice(atr * k, priceDecimals) : "";
  useEffect(() => {
    if (atrMode && state.atrStep !== atrStep) onStateChange({ ...state, atrStep });
  }, [atrMode, atrStep, state, onStateChange]);
  // MS24: the Chop reading, kept in the state so Start sends it.
  const chop = useChop(sym, bookMid, input.tick);
  useEffect(() => {
    if (!sameChop(state.chop, chop)) onStateChange({ ...state, chop });
  }, [chop, state, onStateChange]);
  const carry = useCarry(market.market_index, position);
  const fillBand = () => {
    if (chop?.bandLow == null || chop.bandHigh == null) return;
    set({
      chaseFloor: formatPrice(chop.bandLow, priceDecimals),
      chaseCeiling: formatPrice(chop.bandHigh, priceDecimals),
    });
  };

  return (
    <FieldGroup className="gap-3">
      <TicketChips
        label="Step"
        ariaLabel="Step kind"
        value={state.stepMode}
        onValueChange={(v) => set({ stepMode: v === "atr" ? "atr" : "fixed" })}
        items={[
          { value: "fixed", label: "Fixed", title: "The Step stays as set for the run" },
          {
            value: "atr",
            label: "ATR",
            title: "The Step follows k × ATR, moving the levels when it is 20% off",
          },
        ]}
      />
      <TicketChips
        label="ATR"
        ariaLabel="ATR timeframe"
        value={state.atrTf}
        onValueChange={(v) => set({ atrTf: v as MassagerAtrTf })}
        items={MASSAGER_ATR_TIMEFRAMES.map((tf) => ({
          value: tf,
          label: tf,
          title: `ATR(14) on closed ${tf} candles`,
        }))}
      />
      {atrMode ? (
        <TicketField
          id="massager-atr-mult"
          label="× ATR"
          value={state.atrMult}
          inputMode="decimal"
          placeholder="0.5"
          sanitize={decimalInput}
          onChange={(v) => set({ atrMult: v })}
          hint={atrStep ? `Step now ${atrStep}` : null}
          chips={{
            value: state.atrMult,
            ariaLabel: "ATR multiple",
            onValueChange: (v) => set({ atrMult: v }),
            items: MASSAGER_ATR_MULTIPLES.map((m) => ({
              value: String(m),
              label: `${atrMultLabel(m)}×`,
              title: `${m} × ATR(14) on ${state.atrTf}`,
            })),
          }}
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
          chips={{
            sticky: false,
            ariaLabel: "Step from ATR",
            onValueChange: (v) => {
              const m = parseFloat(v);
              if (atr == null || !Number.isFinite(m)) return;
              set({ step: formatPrice(atr * m, priceDecimals) });
            },
            items: MASSAGER_ATR_MULTIPLES.map((m) => ({
              value: String(m),
              label: `${atrMultLabel(m)}× ATR`,
              title:
                atr == null
                  ? "ATR not loaded yet"
                  : `${formatPrice(atr * m, priceDecimals)}: ${m} × ATR(14) on ${state.atrTf}`,
            })),
          }}
        />
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-sm text-muted-foreground">
        <Fact label="Chop 1h">
          {chop == null ? "…" : `${chopLabelText(chop.label)} ${chop.er.toFixed(2)}`}
        </Fact>
        {chop?.bandLow != null && chop.bandHigh != null ? (
          <>
            <Fact label="Last 24h">
              {marketPrice(chop.bandLow, sym)} to {marketPrice(chop.bandHigh, sym)}
            </Fact>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={fillBand}
              title="Fill the Band with the last 24 closed 1h candles' range"
            >
              Use as Band
            </Button>
          </>
        ) : (
          chop && <span>Price is outside the last 24h range</span>
        )}
      </div>
      <BandFields
        idPrefix="massager"
        market={market}
        bookMid={bookMid}
        floor={state.chaseFloor}
        ceiling={state.chaseCeiling}
        onChange={set}
      />
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-sm text-muted-foreground">
        <Fact label={`ATR ${state.atrTf}`}>{atr == null ? "…" : marketPrice(atr, sym)}</Fact>
        <Fact label="Core">{position === 0 ? "no Position" : formatSize(position)}</Fact>
        {position !== 0 && carry && (
          <Fact label="Tally">
            {carry.carried && !state.fresh
              ? `carries ${carry.source ?? "the last run"}: Basis ${marketPrice(carry.basis, sym)}, ` +
                `captured ${formatSigned(parseFloat(carry.captured ?? "0") || 0)}, ` +
                `run ${(carry.runs ?? 1)}`
              : state.fresh
                ? "new, started fresh"
                : `new: ${carry.why}`}
          </Fact>
        )}
        {preview && (
          <>
            <Fact label="Position">
              {formatSize(preview.positionLow)} to {formatSize(preview.positionHigh)}
            </Fact>
            <Fact label="Center">{marketPrice(preview.center, sym)}</Fact>
            <Fact label="Levels">{preview.levels} each side</Fact>
            <Fact label="Clip">{formatSize(preview.clip)}</Fact>
            {preview.swing < sizeNum - 1e-9 && (
              <Fact label="Swing used">{formatSize(preview.swing)}</Fact>
            )}
            <Fact label="Per round trip">{formatUsd(preview.perRoundTrip)}</Fact>
            <Fact label="Catch-up">
              {preview.catchUp.side
                ? `${preview.catchUp.side} ${formatSize(preview.catchUp.qty)} at the touch`
                : "none"}
            </Fact>
          </>
        )}
      </div>
      {position !== 0 && carry?.carried && (
        <ToggleRow
          id="massager-fresh"
          label="Start a new Tally"
          checked={state.fresh}
          onCheckedChange={(on) => set({ fresh: on })}
        />
      )}
      <p className="text-sm leading-snug text-muted-foreground">
        {refusal ?? (
          <>
            The Swing is how far the Position may move off its Core either way; the Step is
            how far apart its quotes are, and the Clip is the Swing split over the levels that
            fit in the Band. Each quote is a Step from its last fill. A Fixed Step stays as set;
            an ATR Step follows k × ATR after each candle closes, once it is 20% off. It sells
            above the Center and buys back below, two levels resting each side, post-only. A 1h
            close outside the Band pauses it and pushes; it holds what it has. Basis counts every
            trade it makes and carries to the next run on this Position. It does not touch your
            Stops: a Stop sized to the Core does not cover the Swing it buys on the way down.
          </>
        )}
      </p>
    </FieldGroup>
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
    rows: Awaited<ReturnType<typeof api.candles>>;
  } | null>(null);
  useEffect(() => {
    let live = true;
    api
      .candles(symbol, "1h", 48)
      .then((rows) => {
        if (live) setCandles({ symbol, rows });
      })
      .catch(() => {
        if (live) setCandles({ symbol, rows: [] });
      });
    return () => {
      live = false;
    };
  }, [symbol]);
  if (candles?.symbol !== symbol) return null;
  return chopReading(candles.rows, { nowMs: Date.now(), mid, tick });
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
