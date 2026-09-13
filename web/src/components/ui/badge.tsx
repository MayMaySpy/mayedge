import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-medium leading-none",
  {
    variants: {
      variant: {
        default: "border-border bg-secondary text-muted-foreground",
        secondary: "border-transparent bg-secondary text-muted-foreground",
        outline: "border-border bg-transparent text-muted-foreground",
        bid: "border-bid/30 bg-bid/10 text-bid",
        ask: "border-ask/30 bg-ask/10 text-ask",
        warn: "border-warn/30 bg-warn/10 text-warn",
        muted: "border-border bg-transparent text-muted-foreground",
        destructive: "border-destructive/30 bg-destructive/10 text-destructive",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
