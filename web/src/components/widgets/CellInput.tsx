import { useState, type ReactNode } from "react";
import { decimalInput } from "@/lib/numbers";
import { cn } from "@/lib/utils";

/**
 * A labelled price or size cell. A `derived` value (one computed from another field)
 * shows what the operator types while focused, and the computed value otherwise.
 */
export function CellInput({
  label,
  value,
  placeholder,
  onChange,
  trailing,
  derived = false,
  className,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (raw: string) => void;
  trailing?: ReactNode;
  derived?: boolean;
  className?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState(value);
  return (
    <label
      className={cn(
        "flex min-w-0 items-center gap-2 bg-elevated/35 px-3 py-2.5 focus-within:bg-elevated/60",
        className
      )}
    >
      <span className="shrink-0 text-sm text-muted-foreground">{label}</span>
      <input
        className="min-w-0 flex-1 bg-transparent text-right font-mono text-base tabular-nums outline-none placeholder:text-muted-foreground"
        inputMode="decimal"
        placeholder={placeholder}
        value={derived && focused ? draft : value}
        onFocus={() => {
          if (!derived) return;
          setDraft(value);
          setFocused(true);
        }}
        onBlur={() => setFocused(false)}
        onChange={(e) => {
          const raw = decimalInput(e.target.value);
          if (derived) setDraft(raw);
          onChange(raw);
        }}
      />
      {trailing}
    </label>
  );
}
