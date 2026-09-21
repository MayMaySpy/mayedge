import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function PanelCloseButton({ onClose, label = "Hide panel" }: { onClose: () => void; label?: string }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-6 shrink-0"
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <X />
    </Button>
  );
}

export function PanelHeader({
  title,
  trailing,
  onClose,
  children,
  className,
}: {
  title: ReactNode;
  trailing?: ReactNode;
  onClose?: () => void;
  children?: ReactNode;
  className?: string;
}) {
  const hasTrailing = trailing != null || onClose != null;

  return (
    <div
      className={cn(
        "panel-drag flex h-8 shrink-0 cursor-move items-center gap-2 border-b border-border px-2",
        className
      )}
    >
      {typeof title === "string" ? (
        <span className="text-base font-medium text-foreground">{title}</span>
      ) : (
        title
      )}
      {children}
      {hasTrailing ? (
        <div className="ml-auto flex min-w-0 items-center gap-2">
          {trailing}
          {onClose ? <PanelCloseButton onClose={onClose} /> : null}
        </div>
      ) : null}
    </div>
  );
}
