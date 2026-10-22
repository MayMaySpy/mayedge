import { TableHead } from "@/components/ui/table";
import type { SortCol, TableSort } from "@/lib/tableSort";
import { cn } from "@/lib/utils";

/** The header cells of a sortable table. A sorting column is a button with an arrow when active. */
export function SortableHeads<K extends string>({
  cols,
  sort,
  onSort,
}: {
  cols: readonly SortCol<K>[];
  sort: TableSort<K>;
  onSort: (key: K) => void;
}) {
  return cols.map((col, i) => {
    const sortKey = col.key;
    return (
      <TableHead
        key={col.label || `col-${i}`}
        title={col.title}
        hideBelow={col.hideBelow}
        className={col.align === "end" ? "text-right" : undefined}
      >
        {sortKey ? (
          <button
            type="button"
            onClick={() => onSort(sortKey)}
            className={cn(
              "inline-flex items-center gap-0.5 hover:text-text",
              col.align === "end" && "ml-auto",
              sort.key === sortKey && "text-text"
            )}
          >
            {col.label}
            {sort.key === sortKey ? (sort.dir === "desc" ? " ↓" : " ↑") : null}
          </button>
        ) : (
          col.label
        )}
      </TableHead>
    );
  });
}
