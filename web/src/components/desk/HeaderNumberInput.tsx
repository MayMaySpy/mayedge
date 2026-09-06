import { ChevronDown, ChevronUp } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function clamp(n: number, min?: number, max?: number) {
  let v = n;
  if (min != null) v = Math.max(min, v);
  if (max != null) v = Math.min(max, v);
  return v;
}

export function HeaderNumberInput({
  id,
  value,
  min,
  max,
  step = 1,
  widthClass,
  onChange,
}: {
  id: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  widthClass: string;
  onChange: (next: number) => void;
}) {
  const bump = (dir: 1 | -1) => {
    onChange(clamp(value + dir * step, min, max));
  };

  return (
    <div className="flex h-6 items-stretch overflow-hidden rounded-sm border border-rule">
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) => {
          const n = e.target.valueAsNumber;
          if (!Number.isFinite(n)) return;
          onChange(clamp(n, min, max));
        }}
        className={cn(
          "h-full border-0 bg-transparent px-1.5 font-mono text-[11px] tabular-nums",
          "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
          widthClass
        )}
      />
      <div className="flex w-4 shrink-0 flex-col border-l border-rule">
        <button
          type="button"
          tabIndex={-1}
          aria-label="Increase"
          className="flex h-1/2 items-center justify-center text-muted hover:bg-elevated hover:text-text"
          onClick={() => bump(1)}
        >
          <ChevronUp className="size-2.5" />
        </button>
        <button
          type="button"
          tabIndex={-1}
          aria-label="Decrease"
          className="flex h-1/2 items-center justify-center border-t border-rule text-muted hover:bg-elevated hover:text-text"
          onClick={() => bump(-1)}
        >
          <ChevronDown className="size-2.5" />
        </button>
      </div>
    </div>
  );
}
