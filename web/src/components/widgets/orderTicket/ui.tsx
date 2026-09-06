import type { ReactNode } from "react";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn, formatPrice } from "@/lib/utils";
import { SLIP_PRESETS } from "./math";

export const ticketLabelClass = "text-[11px] font-medium font-sans text-muted";

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
  hideLabel,
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
  hideLabel?: boolean;
}) {
  return (
    <Field className={cn("gap-0.5", className)}>
      {hideLabel ? null : (
        <FieldLabel htmlFor={id} className={ticketLabelClass}>
          {label}
        </FieldLabel>
      )}
      <InputGroup className="h-8">
        <InputGroupInput
          id={id}
          value={value}
          inputMode={inputMode}
          onChange={(e) => onChange(sanitize ? sanitize(e.target.value) : e.target.value)}
          className="h-8 font-mono text-sm tabular-nums"
          placeholder={placeholder}
          aria-label={label}
        />
        {addon != null ? (
          <InputGroupAddon align="inline-end">
            {typeof addon === "string" ? (
              <InputGroupText className="text-[11px] font-sans text-muted">{addon}</InputGroupText>
            ) : (
              addon
            )}
          </InputGroupAddon>
        ) : null}
      </InputGroup>
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
    <div className="flex items-center gap-1">
      <ToggleGroup
        type="single"
        variant="seg"
        size="sm"
        spacing={0}
        value={presetValue}
        onValueChange={(v) => {
          if (v) onChange(v);
        }}
        className="min-w-0 flex-1"
        aria-label="Slippage"
      >
        {SLIP_PRESETS.map((p) => (
          <ToggleGroupItem key={p} value={String(p)} className="h-6 min-w-0 flex-1 px-0.5 text-[11px]">
            {p}%
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted">
        {worst != null ? formatPrice(worst) : "—"}
      </span>
    </div>
  );
}
