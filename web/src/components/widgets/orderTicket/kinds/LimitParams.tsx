import { FieldGroup } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatPrice } from "@/lib/utils";
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
  const book = [
    { key: "bid", label: "bid", px: bid > 0 ? bid : null },
    { key: "mid", label: "mid", px: mid != null && mid > 0 ? mid : null },
    { key: "ask", label: "ask", px: ask > 0 ? ask : null },
  ] as const;

  return (
    <FieldGroup className="gap-3">
      <TicketField
        id="limit-price"
        label="Price"
        value={price}
        inputMode="decimal"
        placeholder="0.00"
        onChange={onPriceChange}
        chips={{
          sticky: false,
          ariaLabel: "Book",
          onValueChange: (key) => {
            const row = book.find((b) => b.key === key);
            if (row?.px != null) onPriceChange(String(row.px));
          },
          items: book.map((b) => ({
            value: b.key,
            disabled: b.px == null,
            label: (
              <>
                {b.label}{" "}
                <span className="font-mono tabular-nums">
                  {b.px != null ? formatPrice(b.px, priceDecimals) : "—"}
                </span>
              </>
            ),
          })),
        }}
      />
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={2}
        value={tif}
        onValueChange={(v) => {
          if (v) onTifChange(v as (typeof TIF_CHIPS)[number]["id"]);
        }}
        aria-label="Time in force"
      >
        {TIF_CHIPS.map((t) => (
          <ToggleGroupItem key={t.id} value={t.id} aria-label={t.hint}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex size-full items-center justify-center">{t.label}</span>
              </TooltipTrigger>
              <TooltipContent>{t.hint}</TooltipContent>
            </Tooltip>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </FieldGroup>
  );
}
