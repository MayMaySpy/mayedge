import { FieldGroup } from "@/components/ui/field";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import { useLiveAccount } from "@/lib/liveData";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import {
  massagerInput,
  massagerPreview,
  massagerRefusal,
  type MassagerParamsState,
} from "@/lib/massager";
import { marketPrice } from "@/lib/marketFormat";
import { formatSize, formatUsd } from "@/lib/utils";
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

  return (
    <FieldGroup className="gap-3">
      <TicketField
        id="massager-clip"
        label="Clip"
        value={state.clip}
        inputMode="decimal"
        placeholder="0"
        addon={sym}
        sanitize={decimalInput}
        onChange={(v) => set({ clip: v })}
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
        <Fact label="Core">{position === 0 ? "no Position" : formatSize(position)}</Fact>
        {preview && (
          <>
            <Fact label="Position">
              {formatSize(preview.positionLow)} to {formatSize(preview.positionHigh)}
            </Fact>
            <Fact label="Center">{marketPrice(preview.center, sym)}</Fact>
            <Fact label="Step">{marketPrice(preview.step, sym)}</Fact>
            <Fact label="Levels">{preview.levels} each side</Fact>
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
            The Swing is how far the Position may move off its Core either way. It sells
            above the Center and buys back below, two levels resting each side, post-only. Outside
            the Band it holds what it has. It does not touch your Stops: a Stop sized to the Core
            does not cover the Swing it buys on the way down.
          </>
        )}
      </p>
    </FieldGroup>
  );
}
