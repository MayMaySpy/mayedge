import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** One algo in the Algos panel: a rule above it, and a side stripe when it is the chart's. */
export function RowFrame({
  emphasize,
  long,
  children,
}: {
  emphasize?: boolean;
  long: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "border-t border-rule px-2 py-2",
        emphasize &&
          (long
            ? "shadow-[inset_2px_0_0_0_var(--color-bid)]"
            : "shadow-[inset_2px_0_0_0_var(--color-ask)]")
      )}
    >
      {children}
    </div>
  );
}

/** The row's head: a chevron, then whatever names the algo. Opens the clip list. */
export function RowToggle({
  expanded,
  onToggle,
  className = "flex w-full min-w-0 items-center gap-2 text-left",
  children,
}: {
  expanded: boolean;
  onToggle: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button type="button" onClick={onToggle} className={className}>
      <ChevronDown
        className={cn(
          "size-3.5 shrink-0 text-muted-foreground transition-transform",
          !expanded && "-rotate-90"
        )}
      />
      {children}
    </button>
  );
}

/** A small action on the row: Resume, Pause, Protect now, Stop. */
export function RowButton({
  busy,
  onClick,
  danger,
  icon,
  title,
  children,
}: {
  busy: boolean;
  onClick: () => void;
  danger?: boolean;
  icon?: ReactNode;
  title?: string;
  children: ReactNode;
}) {
  return (
    <Button
      type="button"
      variant={danger ? "danger" : "outline"}
      size="sm"
      disabled={busy}
      onClick={onClick}
      className={cn("h-6 px-1.5", icon && "gap-1")}
      title={title}
    >
      {icon}
      {children}
    </Button>
  );
}

/** Why the algo waits, or what went wrong. */
export function RowNote({ text, tone }: { text: string | null | undefined; tone?: "error" | "warn" }) {
  if (!text) return null;
  return (
    <div
      className={cn(
        "mt-1 truncate font-mono text-sm",
        tone === "error" ? "text-ask" : tone === "warn" ? "text-warn" : "text-muted-foreground"
      )}
    >
      {text}
    </div>
  );
}

/** One line in the opened clip list: a coloured label, then the detail. */
export function ClipLine({
  label,
  labelClass,
  children,
}: {
  label: ReactNode;
  labelClass: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2 font-mono text-xs">
      <span className={labelClass}>{label}</span>
      {children}
    </div>
  );
}
