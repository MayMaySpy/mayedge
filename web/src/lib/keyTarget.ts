/** A key pressed while typing, or with a dialog or popover open, is not for the chart. */
export function keyBlocked(target: EventTarget | null, root: ParentNode = document): boolean {
  if (target instanceof Element && target.closest("input, textarea, select, [contenteditable='true']")) {
    return true;
  }
  return (
    root.querySelector(
      "[role='dialog'][data-state='open'], [data-slot='popover-content'][data-state='open']",
    ) != null
  );
}
