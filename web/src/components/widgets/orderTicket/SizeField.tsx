import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
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
}: SizeFieldProps) {
  const activePct =
    SIZE_PCTS.find(
      (pct) => maxSize > 0 && Math.abs(sizeNum / maxSize - pct / 100) < 0.02
    ) ?? null;

  return (
    <div className="flex flex-col gap-1">
      <TicketField
        id="ticket-size"
        label="Size"
        value={size}
        inputMode="decimal"
        placeholder="0.00"
        addon={symbol}
        onChange={onSizeChange}
      />
      <ToggleGroup
        type="single"
        variant="seg"
        size="sm"
        spacing={0}
        value={activePct != null ? String(activePct) : ""}
        onValueChange={(v) => {
          if (v) onSizePct(Number(v));
        }}
        className="w-full"
      >
        {SIZE_PCTS.map((pct) => (
          <ToggleGroupItem
            key={pct}
            value={String(pct)}
            className="h-6 min-w-0 flex-1 px-0.5 text-[11px]"
            title={
              pct === 100
                ? `${maxTitle}${maxSize > 0 ? ` (${trimQty(maxSize, decimals)})` : ""}`
                : undefined
            }
          >
            {pct === 100 ? "max" : pct}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}
