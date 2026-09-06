import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatPrice } from "@/lib/utils";
import { TIF_CHIPS } from "../math";
import { TicketField } from "../ui";

interface LimitParamsProps {
  price: string;
  bid: number;
  ask: number;
  mid: number | null;
  priceDecimals: number;
  tif: string;
  onPriceChange: (raw: string) => void;
  onTifChange: (tif: (typeof TIF_CHIPS)[number]["id"]) => void;
}

function BookChip({
  label,
  value,
  priceDecimals,
  onClick,
}: {
  label: string;
  value: number | null;
  priceDecimals: number;
  onClick: () => void;
}) {
  const ready = value != null && value > 0;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={!ready}
      className={cn("h-6 min-w-0 flex-1 gap-1 px-1", !ready && "opacity-40")}
      onClick={onClick}
    >
      <span className="text-[11px] font-sans text-muted">{label}</span>
      <span className="font-mono text-[11px] tabular-nums text-text">
        {ready ? formatPrice(value, priceDecimals) : "—"}
      </span>
    </Button>
  );
}

export function LimitParams({
  price,
  bid,
  ask,
  mid,
  priceDecimals,
  tif,
  onPriceChange,
  onTifChange,
}: LimitParamsProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <TicketField
        id="limit-price"
        label="Price"
        value={price}
        inputMode="decimal"
        placeholder="0.00"
        onChange={onPriceChange}
      />
      <div className="flex gap-0.5">
        <BookChip
          label="bid"
          value={bid > 0 ? bid : null}
          priceDecimals={priceDecimals}
          onClick={() => onPriceChange(String(bid))}
        />
        <BookChip
          label="mid"
          value={mid}
          priceDecimals={priceDecimals}
          onClick={() => mid != null && onPriceChange(String(mid))}
        />
        <BookChip
          label="ask"
          value={ask > 0 ? ask : null}
          priceDecimals={priceDecimals}
          onClick={() => onPriceChange(String(ask))}
        />
      </div>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        value={tif}
        onValueChange={(v) => {
          if (v) onTifChange(v as (typeof TIF_CHIPS)[number]["id"]);
        }}
        className="w-full"
        aria-label="Time in force"
      >
        {TIF_CHIPS.map((t) => (
          <Tooltip key={t.id}>
            <TooltipTrigger asChild>
              <ToggleGroupItem
                value={t.id}
                className="h-6 min-w-0 flex-1 rounded-none px-1 text-[11px] first:rounded-l-sm last:rounded-r-sm"
                aria-label={t.hint}
              >
                {t.label}
              </ToggleGroupItem>
            </TooltipTrigger>
            <TooltipContent>{t.hint}</TooltipContent>
          </Tooltip>
        ))}
      </ToggleGroup>
    </div>
  );
}
