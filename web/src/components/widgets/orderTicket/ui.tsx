import type { ReactNode } from "react";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn, formatPrice } from "@/lib/utils";
import { SLIP_PRESETS } from "./math";

export type TicketChipItem = {
  value: string;
  label: ReactNode;
  title?: string;
  disabled?: boolean;
};

export type TicketChipSet = {
  value?: string;
  onValueChange: (value: string) => void;
  items: TicketChipItem[];
  /** Sticky toggle (size %). False = one-shot buttons (bid/mid/ask). */
  sticky?: boolean;
  ariaLabel?: string;
  trailing?: ReactNode;
};

export function TicketField({
  id,
  label,
  value,
  onChange,
  addon,
  inputMode,
  placeholder,
  sanitize,
  className,
  hint,
  hintWarn,
  chips,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (raw: string) => void;
  addon?: ReactNode;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
  placeholder?: string;
  sanitize?: (raw: string) => string;
  className?: string;
  hint?: string | null;
  hintWarn?: boolean;
  chips?: TicketChipSet;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <Field data-invalid={hintWarn || undefined}>
        <FieldLabel htmlFor={id} className="sr-only">
          {label}
        </FieldLabel>
        <InputGroup>
          <InputGroupAddon align="inline-start">
            <InputGroupText className="text-xs font-normal">{label}</InputGroupText>
          </InputGroupAddon>
          <InputGroupInput
            id={id}
            value={value}
            inputMode={inputMode}
            onChange={(e) => onChange(sanitize ? sanitize(e.target.value) : e.target.value)}
            placeholder={placeholder}
            aria-label={label}
            aria-invalid={hintWarn || undefined}
            aria-describedby={hint ? `${id}-hint` : undefined}
            className="text-right font-mono tabular-nums"
          />
          {addon != null ? (
            <InputGroupAddon align="inline-end">
              {typeof addon === "string" ? <InputGroupText>{addon}</InputGroupText> : addon}
            </InputGroupAddon>
          ) : null}
        </InputGroup>
        {hint ? (
          <FieldDescription
            id={`${id}-hint`}
            title={hint}
            className={cn("truncate", hintWarn && "text-destructive")}
          >
            {hint}
          </FieldDescription>
        ) : null}
      </Field>
      {chips ? <TicketChips {...chips} /> : null}
    </div>
  );
}

export function TicketChips({
  label,
  value,
  onValueChange,
  items,
  trailing,
  className,
  ariaLabel,
  sticky = true,
}: {
  label?: string;
  value?: string;
  onValueChange: (value: string) => void;
  items: TicketChipItem[];
  trailing?: ReactNode;
  className?: string;
  ariaLabel?: string;
  sticky?: boolean;
}) {
  const aria = ariaLabel ?? label ?? "Options";

  return (
    <Field
      orientation={label ? "horizontal" : "vertical"}
      className={cn(label ? "w-full items-center gap-1" : "gap-1", className)}
    >
      {label ? <FieldLabel className="flex-none">{label}</FieldLabel> : null}
      <ToggleGroup
        type="single"
        variant="ghost"
        size="sm"
        spacing={1}
        value={sticky ? (value ?? "") : ""}
        onValueChange={(v) => {
          if (v) onValueChange(v);
        }}
        aria-label={aria}
        className="w-full min-w-0"
      >
        {items.map((item) => (
          <ToggleGroupItem
            key={item.value}
            value={item.value}
            title={item.title}
            disabled={item.disabled}
            className="h-6 min-w-0 flex-1 px-1"
          >
            <span className="truncate">{item.label}</span>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {trailing}
    </Field>
  );
}

export function SlipControl({
  slippagePct,
  worst,
  onChange,
}: {
  slippagePct: string;
  worst: number | null;
  onChange: (raw: string) => void;
}) {
  const n = parseFloat(slippagePct) || 0;
  const presetValue = SLIP_PRESETS.includes(n) ? String(n) : "";

  return (
    <TicketChips
      label="Slippage"
      value={presetValue}
      onValueChange={onChange}
      items={SLIP_PRESETS.map((p) => ({ value: String(p), label: `${p}%` }))}
      trailing={
        worst != null ? (
          <FieldDescription className="font-mono tabular-nums">{formatPrice(worst)}</FieldDescription>
        ) : null
      }
    />
  );
}
