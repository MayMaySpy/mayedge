import { useState } from "react";
import type { HideBelow } from "@/components/ui/table";

export type SortDir = "asc" | "desc";
export type TableSort<K extends string> = { key: K; dir: SortDir };

export type SortCol<K extends string> = {
  /** The sort this column sets, or null for a column that does not sort. */
  key: K | null;
  label: string;
  align: "start" | "end";
  title?: string;
  hideBelow?: HideBelow;
};

function loadSort<K extends string>(storageKey: string, keys: readonly K[], fallback: K): TableSort<K> {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) ?? "null") as TableSort<K> | null;
    if (parsed && keys.includes(parsed.key) && (parsed.dir === "asc" || parsed.dir === "desc")) {
      return parsed;
    }
  } catch {
    /* ignore */
  }
  return { key: fallback, dir: "desc" };
}

/** A table's sort, kept in this browser. Picking the sorted column again flips its direction. */
export function useStoredSort<K extends string>(
  storageKey: string,
  keys: readonly K[],
  fallback: K
): [TableSort<K>, (key: K) => void] {
  const [sort, setSort] = useState(() => loadSort(storageKey, keys, fallback));
  const pick = (key: K) => {
    const next: TableSort<K> =
      sort.key === key ? { key, dir: sort.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" };
    setSort(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };
  return [sort, pick];
}

/** Order two rows by their sort values: a missing value goes last, a tie goes by symbol. */
export function compareSortValues(
  a: { symbol: string },
  b: { symbol: string },
  av: number | null,
  bv: number | null,
  dir: SortDir
): number {
  if (av == null && bv == null) return a.symbol.localeCompare(b.symbol);
  if (av == null) return 1;
  if (bv == null) return -1;
  if (av === bv) return a.symbol.localeCompare(b.symbol);
  return (av < bv ? -1 : 1) * (dir === "asc" ? 1 : -1);
}
