import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bid disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default: "text-muted hover:text-text",
        outline: "border border-input bg-transparent text-muted hover:bg-elevated hover:text-text",
        ghost: "text-muted hover:text-text",
        /* Primary desk actions: solid bid/ask for at-a-glance. */
        buy: "bg-bid text-canvas font-semibold hover:brightness-110",
        sell: "bg-ask text-white font-semibold hover:brightness-110",
        danger: "text-ask hover:text-ask hover:brightness-125",
      },
      size: {
        default: "h-8 px-3",
        sm: "h-7 px-2 text-[11px]",
        lg: "h-9 px-4",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  }
);
Button.displayName = "Button";

export { Button };
