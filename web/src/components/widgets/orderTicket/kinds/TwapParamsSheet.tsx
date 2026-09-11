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
  type TwapStyle,
} from "@/lib/algos";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import { parseDecimal } from "@/lib/numbers";
import { formatPrice } from "@/lib/utils";
import { trimQty } from "../math";
import { TicketChips, TicketField } from "../ui";

const digits = (raw: string) => raw.replace(/[^\d]/g, "");
const STYLES: { value: TwapStyle; label: string }[] = [
  { value: "passive", label: "Passive" },
  { value: "neutral", label: "Neutral" },
  { value: "aggressive", label: "Aggressive" },
];

export interface TwapParamsState {
  twapHours: string;
  twapMinutes: string;
  twapMaxPrice: string;
  twapAdvanced: boolean;
  twapRandomize: boolean;
  twapStyle: TwapStyle;
  twapFreq: string;
  twapIndexPct: string;
}

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

export function TwapParamsSheet({
  market,
  bookMid,
  sizeNum,
  state,
  onStateChange,
}: AlgoParamsSheetProps<TwapParamsState>) {
  const set = (patch: Partial<TwapParamsState>) => onStateChange({ ...state, ...patch });
  const decimals = market.size_decimals ?? 4;
  const priceDecimals = market.price_decimals ?? 4;
  const twapSec = twapDurationSeconds(state.twapHours, state.twapMinutes);
  const freqNum = parseDecimal(state.twapFreq) ?? TWAP_DEFAULT_FREQ;
  const sliceSec = state.twapAdvanced ? freqNum : 30;
  const orders = twapSec != null ? twapOrderCount(twapSec, sliceSec) : 0;
  const slice =
    twapSec != null && sizeNum > 0 && orders > 0 ? trimQty(sizeNum / orders, decimals) : "—";
  const sliceLabel =
    state.twapAdvanced && state.twapRandomize && slice !== "—" ? `${slice} (±30%)` : slice;
  const freqLabel = state.twapAdvanced
    ? twapFreqLabel(freqNum > 0 ? freqNum : TWAP_DEFAULT_FREQ, state.twapRandomize)
    : "30s";
  const indexPreset = TWAP_INDEX_PCTS.includes(
    parseFloat(state.twapIndexPct) as (typeof TWAP_INDEX_PCTS)[number]
  )
    ? state.twapIndexPct
    : "";

  return (
    <FieldGroup className="gap-3">
      <ToggleRow
        id="twap-advanced"
        label="Advanced"
        checked={state.twapAdvanced}
        onCheckedChange={(on) => set({ twapAdvanced: on })}
      />
      <div className="flex flex-col gap-1">
        <p className="text-xs text-muted">Running Time (1m – 30d)</p>
        <FieldGroup className="grid grid-cols-2 gap-1">
          <TicketField
            id="twap-hours"
            label="Hours"
            value={state.twapHours}
            inputMode="numeric"
            placeholder="0"
            sanitize={digits}
            onChange={(v) => set({ twapHours: v })}
          />
          <TicketField
            id="twap-minutes"
            label="Minutes"
            value={state.twapMinutes}
            inputMode="numeric"
            placeholder="0"
            sanitize={digits}
            onChange={(v) => set({ twapMinutes: v })}
          />
        </FieldGroup>
      </div>
      {state.twapAdvanced ? (
        <>
          <ToggleRow
            id="twap-randomize"
            label="Randomize"
            checked={state.twapRandomize}
            onCheckedChange={(on) => set({ twapRandomize: on })}
          />
          <TicketChips
            label="Style"
            ariaLabel="TWAP style"
            value={state.twapStyle}
            onValueChange={(v) => {
              if (v === "passive" || v === "neutral" || v === "aggressive") set({ twapStyle: v });
            }}
            items={STYLES.map((s) => ({ value: s.value, label: s.label }))}
          />
          <TicketField
            id="twap-freq"
            label="Slice frequency"
            value={state.twapFreq}
            inputMode="numeric"
            placeholder={String(TWAP_DEFAULT_FREQ)}
            addon="s"
            sanitize={digits}
            onChange={(v) => set({ twapFreq: v })}
          />
        </>
      ) : null}
      <TicketField
        id="twap-max-price"
        label="Max Price"
        value={state.twapMaxPrice}
        inputMode="decimal"
        placeholder="Optional"
        addon="USDC"
        onChange={(v) => set({ twapMaxPrice: v })}
        chips={{
          sticky: false,
          ariaLabel: "Max price",
          onValueChange: (v) => {
            const pct = parseFloat(v);
            if (!Number.isFinite(pct) || !(bookMid != null && bookMid > 0)) return;
            set({ twapMaxPrice: formatPrice(bookMid * (1 + pct / 100), priceDecimals) });
          },
          items: TWAP_MAX_PRICE_PCTS.map((pct) => ({
            value: String(pct),
            label: `${pct}%`,
          })),
        }}
      />
      {state.twapAdvanced ? (
        <TicketField
          id="twap-index-pct"
          label="Max % Past Index"
          value={state.twapIndexPct}
          inputMode="decimal"
          placeholder="Optional"
          addon="%"
          onChange={(v) => set({ twapIndexPct: v })}
          chips={{
            sticky: false,
            ariaLabel: "Max percent past index",
            value: indexPreset,
            onValueChange: (v) => set({ twapIndexPct: v }),
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
    </FieldGroup>
  );
}
