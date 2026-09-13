import { cn } from "@/lib/utils";

function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-border bg-secondary px-1 font-sans text-[10px] font-medium text-muted-foreground",
        className
      )}
      {...props}
    />
  );
}

function KbdGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="kbd-group" className={cn("inline-flex items-center gap-1", className)} {...props} />
  );
}

export { Kbd, KbdGroup };
