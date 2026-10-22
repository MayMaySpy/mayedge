import { useCallback, useEffect, useState } from "react";
import { notifyErr } from "@/lib/notify";

export type HistoryPage<T> = { rows: T[]; next_cursor: string | null };
type Query = { market_index: number | null; cursor?: string; limit: number };

const PAGE = 50;
const NONE: never[] = [];

/**
 * One account history list, 50 rows a page, for all markets or one. It loads when the
 * tab is active and again whenever the market changes. `what` names it in errors.
 */
export function usePagedHistory<T>(
  fetchPage: (q: Query) => Promise<HistoryPage<T>>,
  { active, marketIndex, what }: { active: boolean; marketIndex: number | undefined; what: string }
) {
  const [page, setPage] = useState<{ key: string | null; rows: T[]; cursor: string | null }>({
    key: null,
    rows: [],
    cursor: null,
  });
  const [loadingMore, setLoadingMore] = useState(false);

  const queryKey = String(marketIndex ?? "all");
  const rows: T[] = page.key === queryKey ? page.rows : NONE;
  const cursor = page.key === queryKey ? page.cursor : null;
  const loading = active && page.key !== queryKey;

  const loadMore = useCallback(async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const result = await fetchPage({ market_index: marketIndex ?? null, cursor, limit: PAGE });
      setPage((prev) => ({
        key: queryKey,
        rows: prev.key === queryKey ? [...prev.rows, ...result.rows] : result.rows,
        cursor: result.next_cursor,
      }));
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : `Failed to load ${what}`);
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, fetchPage, marketIndex, queryKey, what]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void (async () => {
      try {
        const result = await fetchPage({ market_index: marketIndex ?? null, limit: PAGE });
        if (cancelled) return;
        setPage({ key: queryKey, rows: result.rows, cursor: result.next_cursor });
      } catch (e) {
        if (cancelled) return;
        notifyErr(e instanceof Error ? e.message : `Failed to load ${what}`);
        setPage({ key: queryKey, rows: [], cursor: null });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, fetchPage, marketIndex, queryKey, what]);

  return { rows, cursor, loading, loadingMore, loadMore };
}

/** A row click that moves the chart to the row's market, or nothing when there is no chart to move. */
export function rowPicksSymbol(
  onSymbolChange: ((symbol: string) => void) | undefined,
  current: string | undefined
) {
  return (symbol: string) =>
    onSymbolChange
      ? () => {
          if (current !== symbol) onSymbolChange(symbol);
        }
      : undefined;
}
