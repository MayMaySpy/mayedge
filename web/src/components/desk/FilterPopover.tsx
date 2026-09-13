import type { ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function FilterPopover({
  label = "Filters",
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="h-6 px-1.5">
          <SlidersHorizontal data-icon="inline-start" />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="top"
        collisionPadding={8}
        className="w-56 border-border bg-popover p-3 shadow-lg ring-1 ring-foreground/10"
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
