import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

/**
 * The width a bar's children want side by side: each child's own content width (so a child that
 * clips or shrinks still counts in full), plus the bar's gaps and padding.
 */
function wantedWidth(el: HTMLElement): number {
  const style = getComputedStyle(el);
  const kids = Array.from(el.children) as HTMLElement[];
  const gap = parseFloat(style.columnGap) || 0;
  const pad = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
  return kids.reduce((sum, kid) => sum + kid.scrollWidth, pad + gap * Math.max(0, kids.length - 1));
}

/**
 * How many of a toolbar's `steps` optional groups fold into its `…` menu. One more folds each
 * time the bar's children want more than its width; one comes back once the bar is as wide as
 * they wanted before that group folded. Group 0 folds first.
 */
export function useToolbarFold(
  ref: RefObject<HTMLElement | null>,
  steps: number,
  /** Anything that changes the bar's content width without resizing it: counts, labels. */
  contentKey = ""
): number {
  const [folded, setFolded] = useState(0);
  const now = useRef(0);
  const need = useRef<number[]>([]);

  const check = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const n = now.current;
    const wanted = wantedWidth(el);
    if (wanted > el.clientWidth + 1 && n < steps) {
      need.current[n] = wanted;
      now.current = n + 1;
      setFolded(n + 1);
    } else if (n > 0 && el.clientWidth >= (need.current[n - 1] ?? Infinity)) {
      now.current = n - 1;
      setFolded(n - 1);
    }
  }, [ref, steps]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, check]);

  // After each fold or new content, until the bar settles: one group at a time, before paint.
  useLayoutEffect(check, [check, folded, contentKey]);

  return folded;
}
