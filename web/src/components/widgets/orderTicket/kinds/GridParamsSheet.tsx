import { FieldGroup } from "@/components/ui/field";
import { parseDecimal, decimalInput } from "@/lib/numbers";
import { useLiveAccount } from "@/lib/liveData";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import { CHASE_BAND_PCTS, chaseBandFromPct } from "../math";
import { TicketChips, TicketField } from "../ui";

const OFFSETS = [1, 4, 8, 12];
const BE_DELAYS = [
  { value: "0", label: "Off", ms: 0 },
  { value: "30000", label: "30s", ms: 30_000 },
  { value: "120000", label: "2m", ms: 120_000 },
  { value: "300000", label: "5m", ms: 300_000 },
] as const;

export interface GridParamsState {
  displayQty: string;
  offsetBps: string;
  profitBps: string;
  gridBps: string;
  gridLinked: boolean;
  chaseFloor: string;
  chaseCeiling: string;
  beDelayMs: string;
}

export function GridParamsSheet({
  market,
  bookMid,
  state,
  onStateChange,
}: AlgoParamsSheetProps<GridParamsState>) {
  const set = (patch: Partial<GridParamsState>) => onStateChange({ ...state, ...patch });
  const offsetNum = parseDecimal(state.offsetBps) ?? parseFloat(state.offsetBps);
  const offsetPreset = OFFSETS.includes(offsetNum) ? String(offsetNum) : "";
  const bePreset = BE_DELAYS.some((d) => d.value === state.beDelayMs) ? state.beDelayMs : "";
  const account = useLiveAccount();
  const makerBps = parseDecimal(account?.maker_fee_bps ?? "0") ?? 0;
  const takerBps = parseDecimal(account?.taker_fee_bps ?? "0") ?? 0;
  const cycleMaker = makerBps * 2;
  const beRoundTrip = makerBps + takerBps;
  const profitNum = parseDecimal(state.profitBps) ?? 0;
  const tier = account?.user_tier || "standard";
  const feeLabel =
    makerBps === 0 && takerBps === 0
      ? `${tier} · 0 maker / 0 taker`
      : `${tier} · ${makerBps.toFixed(2)} maker / ${takerBps.toFixed(2)} taker bp`;

  return (
    <FieldGroup className="gap-3">
      <FieldGroup className="grid grid-cols-2 items-start gap-3">
        <TicketField
          id="grid-clip"
          label="Clip"
          value={state.displayQty}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => set({ displayQty: v })}
        />
        <TicketField
          id="grid-offset"
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
          id="grid-profit"
          label="Profit"
          value={state.profitBps}
          inputMode="decimal"
          placeholder="40"
          addon="bp"
          sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
          onChange={(v) => {
            const patch: Partial<GridParamsState> = { profitBps: v };
            if (state.gridLinked) patch.gridBps = v;
            set(patch);
          }}
        />
        <TicketField
          id="grid-step"
          label="Grid"
          value={state.gridBps}
          inputMode="decimal"
          placeholder="40"
          addon="bp"
          sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
          onChange={(v) => set({ gridBps: v, gridLinked: false })}
        />
      </FieldGroup>
      <FieldGroup className="grid grid-cols-2 gap-3">
        <TicketField
          id="grid-floor"
          label="Floor"
          value={state.chaseFloor}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => set({ chaseFloor: v })}
        />
        <TicketField
          id="grid-ceil"
          label="Ceiling"
          value={state.chaseCeiling}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
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
      <FieldGroup className="gap-2">
        <span className="text-[10px] uppercase tracking-wide text-muted">B/E after merge</span>
        <TicketChips
          ariaLabel="Break-even delay"
          value={bePreset}
          onValueChange={(v) => set({ beDelayMs: v })}
          items={BE_DELAYS.map((d) => ({ value: d.value, label: d.label }))}
        />
      </FieldGroup>
      <p className="text-[10px] leading-snug text-muted">
        Cap is max inventory per side. Clip chases the open side; profit orders close
        the other (max 3 live, then merge). Grid is the re-entry cell — not chase spacing.
        {profitNum > 0 && cycleMaker > 0 && profitNum + 1e-9 < cycleMaker
          ? ` Profit ${profitNum} bp is below maker round-trip (${cycleMaker.toFixed(2)} bp).`
          : beRoundTrip > 0
            ? ` B/E uses maker+taker (${beRoundTrip.toFixed(2)} bp).`
            : " B/E is true VWAP (no fees)."}{" "}
        {feeLabel}.
      </p>
    </FieldGroup>
  );
}
