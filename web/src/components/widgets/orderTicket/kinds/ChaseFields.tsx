import { FieldGroup } from "@/components/ui/field";
import type { Market } from "@/lib/api";
import { bpInput, decimalInput, parseDecimal } from "@/lib/numbers";
import { CHASE_BAND_PCTS, chaseBandFromPct } from "../math";
import { TicketChips, TicketField } from "../ui";

const OFFSETS = [1, 4, 8, 12];

/** Clip size and the offset behind the touch, with offset presets. Chase and Grid. */
export function ClipOffsetFields({
  idPrefix,
  displayQty,
  offsetBps,
  onChange,
}: {
  idPrefix: string;
  displayQty: string;
  offsetBps: string;
  onChange: (patch: { displayQty?: string; offsetBps?: string }) => void;
}) {
  const offsetNum = parseDecimal(offsetBps) ?? parseFloat(offsetBps);
  const offsetPreset = OFFSETS.includes(offsetNum) ? String(offsetNum) : "";
  return (
    <>
      <FieldGroup className="grid grid-cols-2 items-start gap-3">
        <TicketField
          id={`${idPrefix}-clip`}
          label="Clip"
          value={displayQty}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => onChange({ displayQty: v })}
        />
        <TicketField
          id={`${idPrefix}-offset`}
          label="Offset"
          value={offsetBps}
          inputMode="decimal"
          placeholder="4"
          addon="bp"
          sanitize={bpInput}
          onChange={(v) => onChange({ offsetBps: v })}
        />
      </FieldGroup>
      <TicketChips
        ariaLabel="Offset"
        value={offsetPreset}
        onValueChange={(v) => onChange({ offsetBps: v })}
        items={OFFSETS.map((b) => ({ value: String(b), label: `${b} bp` }))}
      />
    </>
  );
}

/** The price band the clips stay inside, with ±% presets around the book. Chase and Grid. */
export function BandFields({
  idPrefix,
  market,
  bookMid,
  floor,
  ceiling,
  onChange,
}: {
  idPrefix: string;
  market: Market;
  bookMid: number | null;
  floor: string;
  ceiling: string;
  onChange: (patch: { chaseFloor?: string; chaseCeiling?: string }) => void;
}) {
  return (
    <>
      <FieldGroup className="grid grid-cols-2 gap-3">
        <TicketField
          id={`${idPrefix}-floor`}
          label="Floor"
          value={floor}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => onChange({ chaseFloor: v })}
        />
        <TicketField
          id={`${idPrefix}-ceil`}
          label="Ceiling"
          value={ceiling}
          inputMode="decimal"
          placeholder="0.00"
          sanitize={decimalInput}
          onChange={(v) => onChange({ chaseCeiling: v })}
        />
      </FieldGroup>
      <TicketChips
        ariaLabel="Band"
        onValueChange={(v) => {
          const pct = parseFloat(v);
          if (!Number.isFinite(pct) || pct <= 0) return;
          const band = chaseBandFromPct(market, pct, bookMid);
          onChange({ chaseFloor: band.floor, chaseCeiling: band.ceiling });
        }}
        items={CHASE_BAND_PCTS.map((pct) => ({
          value: String(pct),
          label: `±${pct}%`,
          title: "Outside band — clips pull until price returns",
        }))}
      />
    </>
  );
}
