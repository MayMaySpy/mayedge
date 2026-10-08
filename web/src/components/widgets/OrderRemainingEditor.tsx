import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Input } from "@/components/ui/input";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import { cn } from "@/lib/utils";

interface OrderRemainingEditorProps {
  initial: string;
  decimals: number;
  disabled?: boolean;
  align?: "left" | "right";
  className?: string;
  style?: CSSProperties;
  onCommit: (trimmed: string) => void;
  onCancel: () => void;
}

export function OrderRemainingEditor({
  initial,
  decimals,
  disabled,
  align = "right",
  className,
  style,
  onCommit,
  onCancel,
}: OrderRemainingEditorProps) {
  const [draft, setDraft] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  const tryCommit = () => {
    const n = parseDecimal(draft);
    if (n == null || n <= 0) return;
    const trimmed = trimQty(n, decimals);
    if (!trimmed) return;
    const before = trimQty(parseDecimal(initial) ?? 0, decimals);
    if (trimmed === before) {
      onCancel();
      return;
    }
    onCommit(trimmed);
  };

  return (
    <Input
      ref={ref}
      value={draft}
      disabled={disabled}
      inputMode="decimal"
      style={style}
      className={cn(
        "h-full w-full rounded-none border-0 bg-transparent px-0 py-0 shadow-none outline-none",
        "focus-visible:border-transparent focus-visible:ring-0",
        align === "left" ? "text-left" : "text-right",
        className
      )}
      onChange={(e) => setDraft(decimalInput(e.target.value))}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          tryCommit();
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
      }}
      onBlur={() => tryCommit()}
    />
  );
}
