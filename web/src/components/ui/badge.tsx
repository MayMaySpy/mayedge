import * as React from "react";
import { cn } from "@/lib/utils";

function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "bid" | "ask" | "muted" | "warn";
}) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 font-mono text-[10px] tracking-wide",
        variant === "default" && "text-muted",
        variant === "bid" && "text-bid",
        variant === "ask" && "text-ask",
        variant === "muted" && "text-muted",
        variant === "warn" && "text-warn",
        className
      )}
      {...props}
    />
  );
}

export { Badge };
