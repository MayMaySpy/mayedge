import { useCallback, useEffect, useRef } from "react";

/** Scroll offset so `row` sits just below a sticky header inside `container`. */
export function scrollTopForRow(opts: {
  scrollTop: number;
  containerTop: number;
  rowTop: number;
  stickyPx: number;
}): number {
  return Math.max(0, opts.scrollTop + (opts.rowTop - opts.containerTop) - opts.stickyPx);
}

export function alignRowToTop(
  container: HTMLElement,
  row: HTMLElement,
  stickyPx: number
): void {
  const c = container.getBoundingClientRect();
  const r = row.getBoundingClientRect();
  container.scrollTop = scrollTopForRow({
    scrollTop: container.scrollTop,
    containerTop: c.top,
    rowTop: r.top,
    stickyPx,
  });
}

/**
 * Keep the selected market's row in view. `onBoard` re-runs the scroll when the row
 * first appears. Returns the scroller's ref and a ref maker for each row.
 */
export function useSelectedRowInView(selected: string, onBoard: boolean) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const rows = useRef<Map<string, HTMLTableRowElement>>(new Map());

  useEffect(() => {
    const container = scrollerRef.current;
    const row = rows.current.get(selected);
    if (!container || !row) return;
    const head = container.querySelector("thead");
    alignRowToTop(container, row, head ? head.getBoundingClientRect().height : 24);
  }, [selected, onBoard]);

  const rowRef = useCallback(
    (symbol: string) => (el: HTMLTableRowElement | null) => {
      const key = symbol.toUpperCase();
      if (el) rows.current.set(key, el);
      else rows.current.delete(key);
    },
    []
  );

  return { scrollerRef, rowRef };
}
