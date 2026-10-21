import { FieldGroup } from "@/components/ui/field";
import { formatPrice } from "@/lib/utils";
import { decimalInput } from "@/lib/numbers";
import { TIF_CHIPS } from "../math";
import { TicketChips, TicketField } from "../ui";

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
        sanitize={decimalInput}
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
      <TicketChips
        ariaLabel="Time in force"
        value={tif}
        onValueChange={(v) => onTifChange(v as (typeof TIF_CHIPS)[number]["id"])}
        items={TIF_CHIPS.map((t) => ({
          value: t.id,
          label: t.label,
          title: t.hint,
        }))}
      />
    </FieldGroup>
  );
}
