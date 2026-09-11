import { useState } from "react";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import { parseDecimal } from "@/lib/numbers";
import { buildLadderPlan } from "@/lib/ladderPlan";
import { makerMinSize } from "../math";
import { TicketChips, TicketField } from "../ui";
import { LadderPreviewDialog } from "./LadderPreviewDialog";

const ORDER_PRESETS = [10, 20, 50];
const WINDOW_PRESETS = [5, 10, 20];
const VAR_PRESETS = [0, 10, 20, 30];

export type LadderSkew = "even" | "low" | "high";

export interface LadderParamsState {
  priceFrom: string;
  priceTo: string;
  orders: string;
  window: string;
  advanced: boolean;
  sizeVarPct: string;
  priceVarPct: string;
  sizeSkew: LadderSkew;
  seed: number;
}

function ladderPreview(state: LadderParamsState, sizeNum: number): string {
  const orders = parseInt(state.orders, 10);
  const window = parseInt(state.window, 10);
  if (!(orders > 0) || !(window > 0) || !(sizeNum > 0)) return "";
  const per = sizeNum / orders;
  const perStr = per >= 1 ? per.toFixed(2).replace(/\.?0+$/, "") : per.toPrecision(3);
  const parts = [`${orders} orders`, `${window} live`, `${perStr}/order`];
  if (state.advanced) {
    const sizeVar = parseDecimal(state.sizeVarPct) ?? 0;
    const distVar = parseDecimal(state.priceVarPct) ?? 0;
    if (sizeVar > 0) parts.push(`±${sizeVar}% size`);
    if (distVar > 0) parts.push(`±${distVar}% dist`);
    if (state.sizeSkew === "low") parts.push("skew low");
    if (state.sizeSkew === "high") parts.push("skew high");
  }
  return parts.join(" · ");
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

export function LadderParamsSheet({
  market,
  bookMid,
  sizeNum,
  state,
  onStateChange,
}: AlgoParamsSheetProps<LadderParamsState>) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const set = (patch: Partial<LadderParamsState>) => onStateChange({ ...state, ...patch });
  const orderPreset = ORDER_PRESETS.includes(parseInt(state.orders, 10)) ? state.orders : "";
  const windowPreset = WINDOW_PRESETS.includes(parseInt(state.window, 10))
    ? state.window
    : "";
  const sizeVarNum = parseDecimal(state.sizeVarPct);
  const distVarNum = parseDecimal(state.priceVarPct);
  const sizeVarPreset = VAR_PRESETS.some((n) => n === sizeVarNum) ? state.sizeVarPct : "";
  const distVarPreset = VAR_PRESETS.some((n) => n === distVarNum) ? state.priceVarPct : "";
  const preview = ladderPreview(state, sizeNum);
  const fromNum = parseDecimal(state.priceFrom) ?? 0;
  const toNum = parseDecimal(state.priceTo) ?? 0;
  const orderCount = parseInt(state.orders, 10);
  const windowNum = parseInt(state.window, 10);
  const priceDecimals = market.price_decimals ?? 4;
  const sizeDecimals = market.size_decimals ?? 4;
  const tick = priceDecimals >= 0 ? 10 ** -priceDecimals : 0.01;
  const qtyStep = sizeDecimals >= 0 ? 10 ** -sizeDecimals : 0.01;
  const mid = bookMid ?? market.mid_price ?? market.mark_price ?? fromNum;
  const minQty = makerMinSize(market.min_base_amount ?? 0, market.min_quote_amount ?? 0, mid);
  const sizeVar = state.advanced ? (parseDecimal(state.sizeVarPct) ?? 0) : 0;
  const priceVar = state.advanced ? (parseDecimal(state.priceVarPct) ?? 0) : 0;
  const sizeSkew =
    state.advanced && state.sizeSkew === "low"
      ? -1
      : state.advanced && state.sizeSkew === "high"
        ? 1
        : 0;
  const planResult =
    sizeNum > 0 && fromNum > 0 && toNum > 0 && fromNum !== toNum && orderCount >= 2
      ? buildLadderPlan({
          qty: sizeNum,
          priceFrom: fromNum,
          priceTo: toNum,
          orders: orderCount,
          tick,
          qtyStep,
          minQty,
          sizeVarPct: sizeVar,
          priceVarPct: priceVar,
          sizeSkew,
          seed: state.seed,
        })
      : { error: "Set from / to prices" };
  const plan = "orders" in planResult ? planResult : null;

  return (
    <FieldGroup className="gap-3">
      <ToggleRow
        id="ladder-advanced"
        label="Advanced"
        checked={state.advanced}
        onCheckedChange={(on) => set({ advanced: on })}
      />
      <FieldGroup className="grid grid-cols-2 gap-3">
        <TicketField
          id="ladder-from"
          label="From"
          value={state.priceFrom}
          inputMode="decimal"
          placeholder="0.00"
          onChange={(v) => set({ priceFrom: v })}
        />
        <TicketField
          id="ladder-to"
          label="To"
          value={state.priceTo}
          inputMode="decimal"
          placeholder="0.00"
          onChange={(v) => set({ priceTo: v })}
        />
      </FieldGroup>
      <FieldGroup className="grid grid-cols-2 items-start gap-3">
        <TicketField
          id="ladder-orders"
          label="Orders"
          value={state.orders}
          inputMode="numeric"
          placeholder="20"
          sanitize={(raw) => raw.replace(/[^\d]/g, "")}
          onChange={(v) => set({ orders: v })}
          chips={{
            ariaLabel: "Orders",
            value: orderPreset,
            onValueChange: (v) => set({ orders: v }),
            items: ORDER_PRESETS.map((n) => ({ value: String(n), label: String(n) })),
          }}
        />
        <TicketField
          id="ladder-window"
          label="Live"
          value={state.window}
          inputMode="numeric"
          placeholder="10"
          sanitize={(raw) => raw.replace(/[^\d]/g, "")}
          onChange={(v) => set({ window: v })}
          chips={{
            ariaLabel: "Live orders",
            value: windowPreset,
            onValueChange: (v) => set({ window: v }),
            items: WINDOW_PRESETS.map((n) => ({ value: String(n), label: String(n) })),
          }}
        />
      </FieldGroup>
      {state.advanced ? (
        <>
          <FieldGroup className="grid grid-cols-2 items-start gap-3">
            <TicketField
              id="ladder-size-var"
              label="Size variance"
              value={state.sizeVarPct}
              inputMode="decimal"
              placeholder="0"
              addon="%"
              sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
              onChange={(v) => set({ sizeVarPct: v })}
              chips={{
                ariaLabel: "Size variance",
                value: sizeVarPreset,
                onValueChange: (v) => set({ sizeVarPct: v }),
                items: VAR_PRESETS.map((n) => ({ value: String(n), label: `${n}` })),
              }}
            />
            <TicketField
              id="ladder-dist-var"
              label="Distance variance"
              value={state.priceVarPct}
              inputMode="decimal"
              placeholder="0"
              addon="%"
              sanitize={(raw) => raw.replace(/[^\d.]/g, "")}
              onChange={(v) => set({ priceVarPct: v })}
              chips={{
                ariaLabel: "Distance variance",
                value: distVarPreset,
                onValueChange: (v) => set({ priceVarPct: v }),
                items: VAR_PRESETS.map((n) => ({ value: String(n), label: `${n}` })),
              }}
            />
          </FieldGroup>
          <TicketChips
            label="Skew"
            ariaLabel="Size skew"
            value={state.sizeSkew}
            onValueChange={(v) => {
              if (v === "even" || v === "low" || v === "high") set({ sizeSkew: v });
            }}
            items={[
              { value: "even", label: "Even" },
              { value: "low", label: "Low", title: "More size at lower prices" },
              { value: "high", label: "High", title: "More size at higher prices" },
            ]}
          />
        </>
      ) : null}
      {preview && (
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 font-mono text-[10px] text-muted">{preview}</p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!plan}
            onClick={() => setPreviewOpen(true)}
            className="h-auto shrink-0 px-1 py-0 text-[10px] font-medium text-muted hover:text-text"
          >
            Preview
          </Button>
        </div>
      )}
      {plan ? (
        <LadderPreviewDialog
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          plan={plan}
          symbol={market.symbol}
          window={Number.isFinite(windowNum) ? windowNum : 0}
          priceDecimals={priceDecimals}
        />
      ) : null}
    </FieldGroup>
  );
}
