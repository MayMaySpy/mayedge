import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * A column's priority, as the table width it drops out under, so a narrow panel keeps the
 * columns that matter: `hideBelow="sm"` hides it while the table is under 24rem. Give a
 * column's head and each of its cells the same value. Numbers never clip; columns go instead.
 */
type HideBelow = "4xs" | "2xs" | "xs" | "sm" | "md" | "lg" | "xl" | "2xl" | "3xl";

const HIDE_BELOW: Record<HideBelow, string> = {
  "4xs": "@max-[12rem]/table:hidden",
  "2xs": "@max-2xs/table:hidden",
  xs: "@max-xs/table:hidden",
  sm: "@max-sm/table:hidden",
  md: "@max-md/table:hidden",
  lg: "@max-lg/table:hidden",
  xl: "@max-xl/table:hidden",
  "2xl": "@max-2xl/table:hidden",
  "3xl": "@max-3xl/table:hidden",
};

/** The thin side stripe a row gets for its side or weight, instead of a tint. */
type RowAccent = "bid" | "ask" | "warn";

const ACCENT: Record<RowAccent, string> = {
  bid: "shadow-[inset_2px_0_0_0_var(--color-bid)]",
  ask: "shadow-[inset_2px_0_0_0_var(--color-ask)]",
  warn: "shadow-[inset_2px_0_0_0_var(--color-warn)]",
};

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div data-slot="table-container" className="@container/table relative w-full">
      <table
        data-slot="table"
        className={cn("w-full caption-bottom border-collapse text-base", className)}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b [&_tr]:border-rule", className)}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("border-t border-rule font-medium", className)}
      {...props}
    />
  );
}

function TableRow({
  className,
  accent,
  ...props
}: React.ComponentProps<"tr"> & { accent?: RowAccent | null }) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-rule/60 transition-colors hover:bg-elevated/25 data-[state=selected]:bg-elevated/40",
        accent && ACCENT[accent],
        className
      )}
      {...props}
    />
  );
}

function TableHead({
  className,
  hideBelow,
  ...props
}: React.ComponentProps<"th"> & { hideBelow?: HideBelow }) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-6 whitespace-nowrap px-2 text-left align-middle font-mono text-sm font-normal text-muted-foreground",
        hideBelow && HIDE_BELOW[hideBelow],
        className
      )}
      {...props}
    />
  );
}

/** Every row is one height: 24px. A button in a cell is `h-6` (or `size-6`) so it does not grow the row. */
function TableCell({
  className,
  hideBelow,
  ...props
}: React.ComponentProps<"td"> & { hideBelow?: HideBelow }) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "h-6 whitespace-nowrap px-2 py-0 align-middle font-mono text-base text-foreground tabular-nums",
        hideBelow && HIDE_BELOW[hideBelow],
        className
      )}
      {...props}
    />
  );
}

/**
 * A market or other name in a cell: the sans face at `text-lg`, cut with an ellipsis when the
 * column is narrow, the whole name in its title.
 */
function TableName({
  className,
  children,
  title,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="table-name"
      title={title ?? (typeof children === "string" ? children : undefined)}
      className={cn("inline-block max-w-32 truncate align-middle font-sans text-lg", className)}
      {...props}
    >
      {children}
    </span>
  );
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-2 text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
  TableName,
  type HideBelow,
  type RowAccent,
};
