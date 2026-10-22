import { TableHead, type HideBelow } from "@/components/ui/table";
import type { SortCol, TableSort } from "@/lib/tableSort";
import { cn } from "@/lib/utils";

/** One sortable header cell: a button, with an arrow while it is the sort. */
export function SortHead<K extends string>({
  label,
  column,
  sort,
  onSort,
  title,
  hideBelow,
  align = "end",
}: {
  label: string;
  column: K;
  sort: TableSort<K>;
  onSort: (key: K) => void;
  title?: string;
  hideBelow?: HideBelow;
  align?: "start" | "end";
}) {
  const active = sort.key === column;
  return (
    <TableHead hideBelow={hideBelow} className={align === "end" ? "text-right" : undefined}>
      <button
        type="button"
        title={title ?? `Sort by ${label}`}
        onClick={() => onSort(column)}
        className={cn(
          "inline-flex items-center gap-0.5 hover:text-text",
          align === "end" && "ml-auto",
          active && "text-text"
        )}
      >
        {label}
        {active ? (sort.dir === "desc" ? " ↓" : " ↑") : null}
      </button>
    </TableHead>
  );
}

/** The header cells of a sortable table. A column with no sort key is a plain label. */
export function SortableHeads<K extends string>({
  cols,
  sort,
  onSort,
}: {
  cols: readonly SortCol<K>[];
  sort: TableSort<K>;
  onSort: (key: K) => void;
}) {
  return cols.map((col, i) =>
    col.key ? (
      <SortHead
        key={col.label || `col-${i}`}
        label={col.label}
        column={col.key}
        sort={sort}
        onSort={onSort}
        title={col.title}
        hideBelow={col.hideBelow}
        align={col.align}
      />
    ) : (
      <TableHead
        key={col.label || `col-${i}`}
        title={col.title}
        hideBelow={col.hideBelow}
        className={col.align === "end" ? "text-right" : undefined}
      >
        {col.label}
      </TableHead>
    )
  );
}
