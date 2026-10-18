import { FieldDescription, FieldGroup } from "@/components/ui/field";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import { trailDistanceLabel, trailReferenceLabel, type TrailDraft } from "@/lib/trail";
import { TicketChips, TicketField } from "../ui";

const DISTANCE_PCTS = [0.5, 1, 2, 3];

export interface TrailParamsState extends TrailDraft {
  expiryMin: string;
}

/** A Trail Entry from the ticket (trail-rules TE1–TE4). Buy and Sell share the sheet. */
export function TrailParamsSheet({ market, state, onStateChange }: AlgoParamsSheetProps<TrailParamsState>) {
  const set = (patch: Partial<TrailParamsState>) => onStateChange({ ...state, ...patch });
  const pctPreset =
    state.distanceKind === "pct" && DISTANCE_PCTS.includes(parseDecimal(state.distance) ?? NaN)
      ? String(parseDecimal(state.distance))
      : "";
  const dist = trailDistanceLabel(state.distance || null, state.distanceKind);
  const act = parseDecimal(state.activation);
  const ref = trailReferenceLabel(state.reference);

  return (
    <FieldGroup className="gap-3">
      <TicketField
        id="trail-distance"
        label="Distance"
        value={state.distance}
        inputMode="decimal"
        placeholder="1"
        sanitize={decimalInput}
        onChange={(v) => set({ distance: v })}
        addon={
          <button
            type="button"
            className="shrink-0 px-1 font-mono text-sm text-muted-foreground hover:text-foreground"
            aria-label={state.distanceKind === "pct" ? "Distance in %; switch to price" : "Distance in price; switch to %"}
            onClick={() => set({ distanceKind: state.distanceKind === "pct" ? "price" : "pct" })}
          >
            {state.distanceKind === "pct" ? "%" : "px"}
          </button>
        }
      />
      <TicketChips
        ariaLabel="Distance"
        value={pctPreset}
        onValueChange={(v) => set({ distance: v, distanceKind: "pct" })}
        items={DISTANCE_PCTS.map((p) => ({ value: String(p), label: `${p}%` }))}
      />
      <FieldGroup className="gap-3">
        <TicketField
          id="trail-activation"
          label="Activate at"
          shortLabel="Activate"
          value={state.activation}
          inputMode="decimal"
          placeholder="Now"
          sanitize={decimalInput}
          onChange={(v) => set({ activation: v })}
        />
        <TicketField
          id="trail-expiry"
          label="Expiry"
          value={state.expiryMin}
          inputMode="numeric"
          placeholder="None"
          addon="min"
          sanitize={(raw) => raw.replace(/[^\d]/g, "")}
          onChange={(v) => set({ expiryMin: v })}
        />
      </FieldGroup>
      <TicketChips
        label="Follows"
        value={state.reference}
        onValueChange={(v) => {
          if (v === "mark" || v === "last") set({ reference: v });
        }}
        items={[
          { value: "mark", label: "Mark" },
          { value: "last", label: "Last", title: "Every trade print, wicks included" },
        ]}
      />
      <FieldDescription className="text-pretty">
        {act != null && act > 0
          ? `Buy waits for ${market.symbol} at or below ${state.activation}, sell at or above it. `
          : ""}
        Then a buy fires when {ref} rises {dist} off its low, a sell when it falls {dist} off its high.
        Market order at your slippage. Follows only while the desk is running.
      </FieldDescription>
    </FieldGroup>
  );
}
