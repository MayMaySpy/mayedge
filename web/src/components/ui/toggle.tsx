import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Toggle as TogglePrimitive } from "radix-ui"

const toggleVariants = cva(
  "group/toggle inline-flex items-center justify-center gap-1 whitespace-nowrap transition-colors outline-none focus-visible:ring-1 focus-visible:ring-bid disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "rounded-sm text-xs hover:bg-elevated hover:text-text data-[state=on]:bg-elevated data-[state=on]:text-text",
        outline:
          "rounded-sm border border-rule text-xs hover:bg-elevated data-[state=on]:bg-elevated data-[state=on]:text-text",
        /* Desk text filters — type weight only, no pill chrome. */
        seg: "rounded-none bg-transparent font-mono text-[10px] text-muted hover:bg-transparent hover:text-text data-[state=on]:bg-transparent data-[state=on]:font-medium data-[state=on]:text-text",
      },
      size: {
        default: "h-8 min-w-8 px-2.5",
        sm: "h-7 min-w-7 px-2 text-[11px]",
        lg: "h-9 min-w-9 px-2.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Toggle({
  className,
  variant = "default",
  size = "default",
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> &
  VariantProps<typeof toggleVariants>) {
  return (
    <TogglePrimitive.Root
      data-slot="toggle"
      className={cn(toggleVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Toggle, toggleVariants }
