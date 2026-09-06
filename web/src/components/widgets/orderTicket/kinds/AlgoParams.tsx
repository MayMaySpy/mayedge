import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  ALGOS,
  formatMinutesLabel,
  TWAP_MINUTE_PRESETS,
  type AlgoId,
} from "@/lib/algos";
import type { Market } from "@/lib/api";
import { parseDecimal } from "@/lib/numbers";
import { CHASE_BAND_PCTS, chaseBandFromPct } from "../math";
import { SlipControl, TicketField } from "../ui";

interface AlgoParamsProps {
  algo: AlgoId;
  market: Market;
  bookMid: number | null;
  displayQty: string;
  offsetBps: string;
  chaseFloor: string;
  chaseCeiling: string;
  twapMinutes: string;
  slippagePct: string;
  worst: number | null;
  onAlgoChange: (id: AlgoId) => void;
  onDisplayQtyChange: (raw: string) => void;
  onOffsetBpsChange: (raw: string) => void;
  onChaseFloorChange: (raw: string) => void;
  onChaseCeilingChange: (raw: string) => void;
  onTwapMinutesChange: (raw: string) => void;
  onSlipChange: (raw: string) => void;
}

const OFFSETS = [1, 4, 8, 12];

export function AlgoParams({
  algo,
  market,
  bookMid,
  displayQty,
  offsetBps,
  chaseFloor,
  chaseCeiling,
  twapMinutes,
  slippagePct,
  worst,
  onAlgoChange,
  onDisplayQtyChange,
  onOffsetBpsChange,
  onChaseFloorChange,
  onChaseCeilingChange,
  onTwapMinutesChange,
  onSlipChange,
}: AlgoParamsProps) {
  const offsetNum = parseDecimal(offsetBps) ?? parseFloat(offsetBps);
  const offsetPreset = OFFSETS.includes(offsetNum) ? String(offsetNum) : "";
  const twapNum = parseFloat(twapMinutes);
  const twapPreset = TWAP_MINUTE_PRESETS.some((m) => m === twapNum) ? String(twapNum) : "";

  return (
    <div className="flex flex-col gap-1.5">
      <ToggleGroup
        type="single"
        variant="seg"
        size="sm"
        spacing={0}
        value={algo}
        onValueChange={(v) => {
          if (v === "chase-iceberg" || v === "twap") onAlgoChange(v);
        }}
        className="w-full"
      >
        {ALGOS.map((a) => (
          <ToggleGroupItem key={a.id} value={a.id} className="h-6 min-w-0 flex-1 px-1 text-[11px]">
            {a.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {algo === "chase-iceberg" ? (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] items-end gap-1">
            <TicketField
              id="algo-clip"
              label="Clip"
              value={displayQty}
              inputMode="decimal"
              placeholder="clip"
              onChange={onDisplayQtyChange}
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-[11px] font-medium text-muted">Offset</span>
              <ToggleGroup
                type="single"
                variant="seg"
                size="sm"
                spacing={0}
                value={offsetPreset}
                onValueChange={(v) => {
                  if (v) onOffsetBpsChange(v);
                }}
                className="w-full"
                aria-label="Offset"
              >
                {OFFSETS.map((b) => (
                  <ToggleGroupItem key={b} value={String(b)} className="h-8 min-w-0 flex-1 px-0.5 text-[11px]">
                    {b}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] font-medium text-muted">Band (work range)</span>
            <ToggleGroup
              type="single"
              variant="seg"
              size="sm"
              spacing={0}
              className="w-full"
              aria-label="Band width"
              onValueChange={(v) => {
                const pct = parseFloat(v);
                if (!Number.isFinite(pct) || pct <= 0) return;
                const band = chaseBandFromPct(market, pct, bookMid);
                onChaseFloorChange(band.floor);
                onChaseCeilingChange(band.ceiling);
              }}
            >
              {CHASE_BAND_PCTS.map((pct) => (
                <ToggleGroupItem
                  key={pct}
                  value={String(pct)}
                  className="h-7 min-w-0 flex-1 px-0.5 text-[10px]"
                >
                  ±{pct}%
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <span className="text-[10px] text-muted">Outside band — clips pull until price returns</span>
          </div>
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1">
            <Input
              id="algo-floor"
              value={chaseFloor}
              inputMode="decimal"
              placeholder="floor"
              aria-label="Floor"
              onChange={(e) => onChaseFloorChange(e.target.value)}
              className="h-8 font-mono text-sm tabular-nums"
            />
            <span className="text-[11px] text-muted">—</span>
            <Input
              id="algo-ceil"
              value={chaseCeiling}
              inputMode="decimal"
              placeholder="ceil"
              aria-label="Ceiling"
              onChange={(e) => onChaseCeilingChange(e.target.value)}
              className="h-8 font-mono text-sm tabular-nums"
            />
          </div>
        </>
      ) : (
        <>
          <div className="flex items-end gap-1">
            <TicketField
              id="algo-duration"
              label="Duration"
              value={twapMinutes}
              inputMode="decimal"
              placeholder="15"
              addon="min"
              className="min-w-0 flex-1"
              sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
              onChange={onTwapMinutesChange}
            />
            <ToggleGroup
              type="single"
              variant="seg"
              size="sm"
              spacing={0}
              value={twapPreset}
              onValueChange={(v) => {
                if (v) onTwapMinutesChange(v);
              }}
              className="mb-px min-w-0 flex-[1.2]"
              aria-label="Duration preset"
            >
              {TWAP_MINUTE_PRESETS.map((m) => (
                <ToggleGroupItem key={m} value={String(m)} className="h-8 min-w-0 flex-1 px-0.5 text-[11px]">
                  {formatMinutesLabel(m)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <SlipControl slippagePct={slippagePct} worst={worst} onChange={onSlipChange} />
        </>
      )}
    </div>
  );
}
