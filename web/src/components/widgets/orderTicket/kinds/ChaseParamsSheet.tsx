import { FieldGroup } from "@/components/ui/field";
import { parseDecimal } from "@/lib/numbers";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import { CHASE_BAND_PCTS, chaseBandFromPct } from "../math";
import { TicketChips, TicketField } from "../ui";

const OFFSETS = [1, 4, 8, 12];

export interface ChaseParamsState {
  displayQty: string;
  offsetBps: string;
  chaseFloor: string;
  chaseCeiling: string;
}

export function ChaseParamsSheet({
  market,
  bookMid,
  state,
  onStateChange,
}: AlgoParamsSheetProps<ChaseParamsState>) {
  const set = (patch: Partial<ChaseParamsState>) => onStateChange({ ...state, ...patch });
  const offsetNum = parseDecimal(state.offsetBps) ?? parseFloat(state.offsetBps);
  const offsetPreset = OFFSETS.includes(offsetNum) ? String(offsetNum) : "";

  return (
    <FieldGroup className="gap-3">
      <FieldGroup className="grid grid-cols-2 items-start gap-3">
        <TicketField
          id="algo-clip"
          label="Clip"
          value={state.displayQty}
          inputMode="decimal"
          placeholder="0.00"
          onChange={(v) => set({ displayQty: v })}
        />
        <TicketField
          id="algo-offset"
          label="Offset"
          value={state.offsetBps}
          inputMode="decimal"
          placeholder="4"
          addon="bp"
          sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
          onChange={(v) => set({ offsetBps: v })}
          chips={{
            ariaLabel: "Offset",
            value: offsetPreset,
            onValueChange: (v) => set({ offsetBps: v }),
            items: OFFSETS.map((b) => ({ value: String(b), label: String(b) })),
          }}
        />
      </FieldGroup>
      <FieldGroup className="grid grid-cols-2 gap-3">
        <TicketField
          id="algo-floor"
          label="Floor"
          value={state.chaseFloor}
          inputMode="decimal"
          placeholder="0.00"
          onChange={(v) => set({ chaseFloor: v })}
        />
        <TicketField
          id="algo-ceil"
          label="Ceiling"
          value={state.chaseCeiling}
          inputMode="decimal"
          placeholder="0.00"
          onChange={(v) => set({ chaseCeiling: v })}
        />
      </FieldGroup>
      <TicketChips
        ariaLabel="Band"
        onValueChange={(v) => {
          const pct = parseFloat(v);
          if (!Number.isFinite(pct) || pct <= 0) return;
          const band = chaseBandFromPct(market, pct, bookMid);
          set({ chaseFloor: band.floor, chaseCeiling: band.ceiling });
        }}
        items={CHASE_BAND_PCTS.map((pct) => ({
          value: String(pct),
          label: `±${pct}%`,
          title: "Outside band — clips pull until price returns",
        }))}
      />
    </FieldGroup>
  );
}
