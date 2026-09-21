import { cva } from "class-variance-authority"

export const toggleVariants = cva(
      "group/toggle inline-flex items-center justify-center gap-1 whitespace-nowrap transition-colors outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "rounded-lg text-base hover:bg-accent hover:text-foreground data-[state=on]:bg-accent data-[state=on]:text-foreground",
        outline:
          "rounded-lg border border-input bg-transparent text-base text-muted-foreground hover:bg-accent hover:text-foreground data-[state=on]:bg-accent data-[state=on]:text-foreground",
        ghost:
          "rounded-md bg-transparent text-base font-normal text-muted-foreground hover:bg-accent hover:text-foreground data-[state=on]:bg-transparent data-[state=on]:font-medium data-[state=on]:text-foreground",
        seg: "rounded-none bg-transparent font-mono text-sm text-muted-foreground hover:bg-transparent hover:text-foreground data-[state=on]:bg-transparent data-[state=on]:font-medium data-[state=on]:text-foreground",
      },
      size: {
        default: "h-8 min-w-8 px-2.5",
        sm: "h-7 min-w-7 px-2 text-sm",
        lg: "h-9 min-w-9 px-2.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)
