import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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
  const input = (
    <InputGroupInput
      id={id}
      value={value}
      inputMode={inputMode}
      onChange={(e) => onChange(sanitize ? sanitize(e.target.value) : e.target.value)}
      placeholder={placeholder}
      aria-label={label}
      aria-invalid={hintWarn || undefined}
      aria-describedby={hint ? `${id}-hint` : undefined}
    />
  );

  const field = (
    <Field className={chips ? undefined : className} data-invalid={hintWarn || undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {addon != null || hint ? (
        <InputGroup>
          {input}
          <InputGroupAddon align="inline-end">
            {hint ? (
              <InputGroupText
                id={`${id}-hint`}
                title={hint}
                className={cn("min-w-0 truncate", hintWarn && "text-destructive")}
              >
                {hint}
              </InputGroupText>
            ) : null}
            {typeof addon === "string" ? <InputGroupText>{addon}</InputGroupText> : addon}
          </InputGroupAddon>
        </InputGroup>
      ) : (
        <Input
          id={id}
          value={value}
          inputMode={inputMode}
          onChange={(e) => onChange(sanitize ? sanitize(e.target.value) : e.target.value)}
          placeholder={placeholder}
          aria-label={label}
          aria-invalid={hintWarn || undefined}
        />
      )}
    </Field>
  );

  if (!chips) return field;

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {field}
      <TicketChips {...chips} />
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

  if (!sticky) {
    return (
      <Field className={cn("gap-1", className)}>
        {label ? <FieldLabel>{label}</FieldLabel> : null}
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={aria}>
          {items.map((item) => (
            <Button
              key={item.value}
              type="button"
              variant="outline"
              size="sm"
              disabled={item.disabled}
              title={item.title}
              onClick={() => onValueChange(item.value)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        {trailing}
      </Field>
    );
  }

  return (
    <Field
      orientation={label ? "horizontal" : "vertical"}
      className={cn(label ? "w-full items-center gap-1" : "gap-1", className)}
    >
      {label ? <FieldLabel className="flex-none">{label}</FieldLabel> : null}
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={2}
        value={value ?? ""}
        onValueChange={(v) => {
          if (v) onValueChange(v);
        }}
        aria-label={aria}
      >
        {items.map((item) => (
          <ToggleGroupItem
            key={item.value}
            value={item.value}
            title={item.title}
            disabled={item.disabled}
          >
            {item.label}
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
          <FieldDescription className="font-mono tabular-nums">
            {formatPrice(worst)}
          </FieldDescription>
        ) : null
      }
    />
  );
}
