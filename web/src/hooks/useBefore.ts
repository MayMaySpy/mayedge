import { useCallback, useSyncExternalStore } from "react";

/**
 * True while the clock is before `untilMs` (epoch ms), and false once it passes, without a new
 * value from the desk. One timeout per deadline; no clock is read during render.
 */
export function useBefore(untilMs: number): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const wait = untilMs - Date.now();
      if (!(wait > 0)) return () => {};
      const id = setTimeout(onChange, wait + 1);
      return () => clearTimeout(id);
    },
    [untilMs]
  );
  const before = useCallback(() => untilMs > Date.now(), [untilMs]);
  return useSyncExternalStore(subscribe, before, before);
}
