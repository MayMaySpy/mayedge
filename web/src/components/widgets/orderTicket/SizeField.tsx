import { Button } from "@/components/ui/button";
import {
  baseToUsd,
  formatUsdNotional,
  SIZE_PCTS,
  type SizeUnit,
  trimQty,
} from "./math";
import { TicketField } from "./ui";
import { decimalInput } from "@/lib/numbers";

interface SizeFieldProps {
  symbol: string;
  size: string;
  sizeNum: number;
  maxSize: number;
  maxTitle: string;
  decimals: number;
  sizeUnit: SizeUnit;
  workingPrice: number | null;
  otherUnitHint: string | null;
  canUseUsd: boolean;
  label?: string;
  onSizeChange: (raw: string) => void;
  onSizePct: (pct: number) => void;
  onUnitToggle: () => void;
  minHint?: string | null;
  minHintWarn?: boolean;
}

export function SizeField({
  symbol,
  size,
  sizeNum,
  maxSize,
  maxTitle,
  decimals,
  sizeUnit,
  workingPrice,
  otherUnitHint,
  canUseUsd,
  onSizeChange,
  onSizePct,
  onUnitToggle,
  minHint,
  minHintWarn,
  label = "Size",
}: SizeFieldProps) {
  const activePct =
    SIZE_PCTS.find(
      (pct) => maxSize > 0 && Math.abs(sizeNum / maxSize - pct / 100) < 0.02
    ) ?? null;

  const hint = minHintWarn ? minHint : (otherUnitHint ?? minHint);

  const maxChipQty =
    maxSize > 0
      ? sizeUnit === "usd" && workingPrice != null && workingPrice > 0
        ? formatUsdNotional(baseToUsd(maxSize, workingPrice))
        : trimQty(maxSize, decimals)
      : "";

  const unitLabel = sizeUnit === "usd" ? "USD" : symbol;
  const unitDisabled = sizeUnit === "base" && !canUseUsd;

  return (
    <TicketField
      id="ticket-size"
      label={label}
      value={size}
      inputMode="decimal"
      placeholder="0.00"
      addon={
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 min-w-0 px-1.5 font-mono text-sm tabular-nums"
          disabled={unitDisabled}
          title={unitDisabled ? "No price" : "Switch size unit"}
          onClick={onUnitToggle}
        >
          {unitLabel}
        </Button>
      }
      hint={hint}
      hintWarn={minHintWarn}
      sanitize={decimalInput}
      onChange={onSizeChange}
      chips={{
        value: activePct != null ? String(activePct) : "",
        onValueChange: (v) => onSizePct(Number(v)),
        items: SIZE_PCTS.map((pct) => ({
          value: String(pct),
          label: pct === 100 ? "max" : `${pct}%`,
          title:
            pct === 100
              ? `${maxTitle}${maxChipQty ? ` (${maxChipQty})` : ""}`
              : undefined,
        })),
      }}
    />
  );
}
