import { SIZE_PCTS, trimQty } from "./math";
import { TicketField } from "./ui";

interface SizeFieldProps {
  symbol: string;
  size: string;
  sizeNum: number;
  maxSize: number;
  maxTitle: string;
  decimals: number;
  onSizeChange: (raw: string) => void;
  onSizePct: (pct: number) => void;
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
  onSizeChange,
  onSizePct,
  minHint,
  minHintWarn,
}: SizeFieldProps) {
  const activePct =
    SIZE_PCTS.find(
      (pct) => maxSize > 0 && Math.abs(sizeNum / maxSize - pct / 100) < 0.02
    ) ?? null;

  return (
    <TicketField
      id="ticket-size"
      label="Size"
      value={size}
      inputMode="decimal"
      placeholder="0.00"
      addon={symbol}
      hint={minHint}
      hintWarn={minHintWarn}
      onChange={onSizeChange}
      chips={{
        value: activePct != null ? String(activePct) : "",
        onValueChange: (v) => onSizePct(Number(v)),
        items: SIZE_PCTS.map((pct) => ({
          value: String(pct),
          label: pct === 100 ? "max" : `${pct}%`,
          title:
            pct === 100
              ? `${maxTitle}${maxSize > 0 ? ` (${trimQty(maxSize, decimals)})` : ""}`
              : undefined,
        })),
      }}
    />
  );
}
