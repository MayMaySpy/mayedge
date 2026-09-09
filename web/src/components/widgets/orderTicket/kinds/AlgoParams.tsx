import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import {
  formatTwapRuntime,
  twapDurationSeconds,
  twapFreqLabel,
  twapOrderCount,
  TWAP_DEFAULT_FREQ,
  TWAP_INDEX_PCTS,
  TWAP_MAX_PRICE_PCTS,
  type AlgoId,
  type TwapStyle,
} from "@/lib/algos";
import type { Market } from "@/lib/api";
import { parseDecimal } from "@/lib/numbers";
import { formatPrice } from "@/lib/utils";
import { CHASE_BAND_PCTS, chaseBandFromPct, trimQty } from "../math";
import { TicketChips, TicketField } from "../ui";

interface AlgoParamsProps {
  algo: AlgoId;
  market: Market;
  bookMid: number | null;
  displayQty: string;
  offsetBps: string;
  chaseFloor: string;
  chaseCeiling: string;
  twapHours: string;
  twapMinutes: string;
  twapMaxPrice: string;
  twapAdvanced: boolean;
  twapRandomize: boolean;
  twapStyle: TwapStyle;
  twapFreq: string;
  twapIndexPct: string;
  sizeNum: number;
  onDisplayQtyChange: (raw: string) => void;
  onOffsetBpsChange: (raw: string) => void;
  onChaseFloorChange: (raw: string) => void;
  onChaseCeilingChange: (raw: string) => void;
  onTwapHoursChange: (raw: string) => void;
  onTwapMinutesChange: (raw: string) => void;
  onTwapMaxPriceChange: (raw: string) => void;
  onTwapAdvancedChange: (on: boolean) => void;
  onTwapRandomizeChange: (on: boolean) => void;
  onTwapStyleChange: (style: TwapStyle) => void;
  onTwapFreqChange: (raw: string) => void;
  onTwapIndexPctChange: (raw: string) => void;
}

const OFFSETS = [1, 4, 8, 12];
const digits = (raw: string) => raw.replace(/[^\d]/g, "");
const STYLES: { value: TwapStyle; label: string }[] = [
  { value: "passive", label: "Passive" },
  { value: "neutral", label: "Neutral" },
  { value: "aggressive", label: "Aggressive" },
];

function TwapRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex w-full justify-between gap-2 text-xs">
      <span className="whitespace-nowrap text-muted">{label}</span>
      <span className="font-mono tabular-nums text-text">{value}</span>
    </div>
  );
}

function ToggleRow({
  id,
  label,
  checked,
  onCheckedChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onCheckedChange: (on: boolean) => void;
}) {
  return (
    <Field orientation="horizontal" className="w-full items-center justify-between gap-2">
      <FieldLabel htmlFor={id} className="text-xs font-normal text-muted">
        {label}
      </FieldLabel>
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={(v) => onCheckedChange(v === true)}
        aria-label={label}
      />
    </Field>
  );
}

export function AlgoParams({
  algo,
  market,
  bookMid,
  displayQty,
  offsetBps,
  chaseFloor,
  chaseCeiling,
  twapHours,
  twapMinutes,
  twapMaxPrice,
  twapAdvanced,
  twapRandomize,
  twapStyle,
  twapFreq,
  twapIndexPct,
  sizeNum,
  onDisplayQtyChange,
  onOffsetBpsChange,
  onChaseFloorChange,
  onChaseCeilingChange,
  onTwapHoursChange,
  onTwapMinutesChange,
  onTwapMaxPriceChange,
  onTwapAdvancedChange,
  onTwapRandomizeChange,
  onTwapStyleChange,
  onTwapFreqChange,
  onTwapIndexPctChange,
}: AlgoParamsProps) {
  const offsetNum = parseDecimal(offsetBps) ?? parseFloat(offsetBps);
  const offsetPreset = OFFSETS.includes(offsetNum) ? String(offsetNum) : "";
  const decimals = market.size_decimals ?? 4;
  const priceDecimals = market.price_decimals ?? 4;
  const twapSec = twapDurationSeconds(twapHours, twapMinutes);
  const freqNum = parseDecimal(twapFreq) ?? TWAP_DEFAULT_FREQ;
  const sliceSec = twapAdvanced ? freqNum : 30;
  const orders = twapSec != null ? twapOrderCount(twapSec, sliceSec) : 0;
  const slice =
    twapSec != null && sizeNum > 0 && orders > 0 ? trimQty(sizeNum / orders, decimals) : "—";
  const sliceLabel = twapAdvanced && twapRandomize && slice !== "—" ? `${slice} (±30%)` : slice;
  const freqLabel = twapAdvanced
    ? twapFreqLabel(freqNum > 0 ? freqNum : TWAP_DEFAULT_FREQ, twapRandomize)
    : "30s";
  const indexPreset = TWAP_INDEX_PCTS.includes(parseFloat(twapIndexPct) as (typeof TWAP_INDEX_PCTS)[number])
    ? twapIndexPct
    : "";

  return (
    <FieldGroup className="gap-3">
      {algo === "chase-iceberg" ? (
        <>
          <FieldGroup className="grid grid-cols-2 items-start gap-3">
            <TicketField
              id="algo-clip"
              label="Clip"
              value={displayQty}
              inputMode="decimal"
              placeholder="0.00"
              onChange={onDisplayQtyChange}
            />
            <TicketField
              id="algo-offset"
              label="Offset"
              value={offsetBps}
              inputMode="decimal"
              placeholder="4"
              addon="bp"
              sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
              onChange={onOffsetBpsChange}
              chips={{
                ariaLabel: "Offset",
                value: offsetPreset,
                onValueChange: onOffsetBpsChange,
                items: OFFSETS.map((b) => ({ value: String(b), label: String(b) })),
              }}
            />
          </FieldGroup>
          <FieldGroup className="grid grid-cols-2 gap-3">
            <TicketField
              id="algo-floor"
              label="Floor"
              value={chaseFloor}
              inputMode="decimal"
              placeholder="0.00"
              onChange={onChaseFloorChange}
            />
            <TicketField
              id="algo-ceil"
              label="Ceiling"
              value={chaseCeiling}
              inputMode="decimal"
              placeholder="0.00"
              onChange={onChaseCeilingChange}
            />
          </FieldGroup>
          <TicketChips
            ariaLabel="Band"
            onValueChange={(v) => {
              const pct = parseFloat(v);
              if (!Number.isFinite(pct) || pct <= 0) return;
              const band = chaseBandFromPct(market, pct, bookMid);
              onChaseFloorChange(band.floor);
              onChaseCeilingChange(band.ceiling);
            }}
            items={CHASE_BAND_PCTS.map((pct) => ({
              value: String(pct),
              label: `±${pct}%`,
              title: "Outside band — clips pull until price returns",
            }))}
          />
        </>
      ) : (
        <>
          <ToggleRow
            id="twap-advanced"
            label="Advanced"
            checked={twapAdvanced}
            onCheckedChange={onTwapAdvancedChange}
          />
          <div className="flex flex-col gap-1">
            <p className="text-xs text-muted">Running Time (1m – 30d)</p>
            <FieldGroup className="grid grid-cols-2 gap-1">
              <TicketField
                id="twap-hours"
                label="Hours"
                value={twapHours}
                inputMode="numeric"
                placeholder="0"
                sanitize={digits}
                onChange={onTwapHoursChange}
              />
              <TicketField
                id="twap-minutes"
                label="Minutes"
                value={twapMinutes}
                inputMode="numeric"
                placeholder="0"
                sanitize={digits}
                onChange={onTwapMinutesChange}
              />
            </FieldGroup>
          </div>
          {twapAdvanced ? (
            <>
              <ToggleRow
                id="twap-randomize"
                label="Randomize"
                checked={twapRandomize}
                onCheckedChange={onTwapRandomizeChange}
              />
              <TicketChips
                label="Style"
                ariaLabel="TWAP style"
                value={twapStyle}
                onValueChange={(v) => {
                  if (v === "passive" || v === "neutral" || v === "aggressive") onTwapStyleChange(v);
                }}
                items={STYLES.map((s) => ({ value: s.value, label: s.label }))}
              />
              <TicketField
                id="twap-freq"
                label="Slice frequency"
                value={twapFreq}
                inputMode="numeric"
                placeholder={String(TWAP_DEFAULT_FREQ)}
                addon="s"
                sanitize={digits}
                onChange={onTwapFreqChange}
              />
            </>
          ) : null}
          <TicketField
            id="twap-max-price"
            label="Max Price"
            value={twapMaxPrice}
            inputMode="decimal"
            placeholder="Optional"
            addon="USDC"
            onChange={onTwapMaxPriceChange}
            chips={{
              sticky: false,
              ariaLabel: "Max price",
              onValueChange: (v) => {
                const pct = parseFloat(v);
                if (!Number.isFinite(pct) || !(bookMid != null && bookMid > 0)) return;
                onTwapMaxPriceChange(formatPrice(bookMid * (1 + pct / 100), priceDecimals));
              },
              items: TWAP_MAX_PRICE_PCTS.map((pct) => ({
                value: String(pct),
                label: `${pct}%`,
              })),
            }}
          />
          {twapAdvanced ? (
            <TicketField
              id="twap-index-pct"
              label="Max % Past Index"
              value={twapIndexPct}
              inputMode="decimal"
              placeholder="Optional"
              addon="%"
              onChange={onTwapIndexPctChange}
              chips={{
                sticky: false,
                ariaLabel: "Max percent past index",
                value: indexPreset,
                onValueChange: onTwapIndexPctChange,
                items: TWAP_INDEX_PCTS.map((pct) => ({
                  value: String(pct),
                  label: `${pct}%`,
                })),
              }}
            />
          ) : null}
          <div className="flex flex-col gap-1.5">
            <TwapRow
              label="Order Size"
              value={sizeNum > 0 ? `${trimQty(sizeNum, decimals)} ${market.symbol}` : "—"}
            />
            <TwapRow label="Frequency" value={freqLabel} />
            <TwapRow label="Runtime" value={twapSec != null ? formatTwapRuntime(twapSec) : "—"} />
            <TwapRow label="Number of Orders" value={orders > 0 ? String(orders) : "—"} />
            <TwapRow label="Size per Suborder" value={sliceLabel} />
          </div>
        </>
      )}
    </FieldGroup>
  );
}
