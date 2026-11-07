import { useEffect, useState } from "react";
import { FieldGroup } from "@/components/ui/field";
import { api } from "@/lib/api";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import { useLiveAccount } from "@/lib/liveData";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import {
  lastAtr,
  MASSAGER_ATR_MULTIPLES,
  MASSAGER_ATR_RESOLUTION,
  massagerInput,
  massagerPreview,
  massagerRefusal,
  type MassagerParamsState,
} from "@/lib/massager";
import { marketPrice } from "@/lib/marketFormat";
import { formatPrice, formatSize, formatUsd } from "@/lib/utils";
import { TicketField } from "../ui";
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
  const atr = useHourAtr(sym);
  const priceDecimals = market.price_decimals ?? 4;

  return (
    <FieldGroup className="gap-3">
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
            const k = parseFloat(v);
            if (atr == null || !Number.isFinite(k)) return;
            set({ step: formatPrice(atr * k, priceDecimals) });
          },
          items: MASSAGER_ATR_MULTIPLES.map((k) => ({
            value: String(k),
            label: `${k === 0.5 ? "½" : k}× ATR`,
            title:
              atr == null
                ? "ATR not loaded yet"
                : `${formatPrice(atr * k, priceDecimals)}: ${k} × ATR(14) on 1h`,
          })),
        }}
      />
      <BandFields
        idPrefix="massager"
        market={market}
        bookMid={bookMid}
        floor={state.chaseFloor}
        ceiling={state.chaseCeiling}
        onChange={set}
      />
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-sm text-muted-foreground">
        <Fact label="ATR 1h">{atr == null ? "…" : marketPrice(atr, sym)}</Fact>
        <Fact label="Core">{position === 0 ? "no Position" : formatSize(position)}</Fact>
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
      <p className="text-sm leading-snug text-muted-foreground">
        {refusal ?? (
          <>
            The Swing is how far the Position may move off its Core either way; the Step is
            how far apart its quotes are, and the Clip is the Swing split over the levels that
            fit in the Band. The Step stays as set for the run. It sells
            above the Center and buys back below, two levels resting each side, post-only. Outside
            the Band it holds what it has. It does not touch your Stops: a Stop sized to the Core
            does not cover the Swing it buys on the way down.
          </>
        )}
      </p>
    </FieldGroup>
  );
}

/** MS19: ATR(14) on 1h candles, for the Step presets. Null until loaded. */
function useHourAtr(symbol: string): number | null {
  const [atr, setAtr] = useState<{ symbol: string; value: number | null } | null>(null);
  useEffect(() => {
    let live = true;
    api
      .candles(symbol, MASSAGER_ATR_RESOLUTION, 100)
      .then((candles) => {
        if (live) setAtr({ symbol, value: lastAtr(candles) });
      })
      .catch(() => {
        if (live) setAtr({ symbol, value: null });
      });
    return () => {
      live = false;
    };
  }, [symbol]);
  return atr?.symbol === symbol ? atr.value : null;
}
