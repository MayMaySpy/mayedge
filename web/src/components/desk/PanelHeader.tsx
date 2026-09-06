import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Small hide control — shared by mosaic headers and chart chrome. */
export function PanelCloseButton({ onClose, label = "Hide panel" }: { onClose: () => void; label?: string }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-5 shrink-0 text-muted hover:text-text"
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

/**
 * Uniform mosaic panel chrome — h-7 drag bar, muted title, optional trailing actions.
 */
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
        "panel-drag flex h-7 shrink-0 cursor-move items-center gap-2 border-b border-rule px-2",
        className
      )}
    >
      {typeof title === "string" ? (
        <span className="text-[11px] font-medium text-muted">{title}</span>
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
