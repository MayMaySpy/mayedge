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
