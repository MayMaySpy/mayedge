/** Throttled change notices for the live stores. */


export function makeThrottledNotify(ms: number) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending = false;
  let lastAt = 0;
  const listeners = new Set<() => void>();

  const flush = () => {
    timer = null;
    lastAt = performance.now();
    if (!pending) return;
    pending = false;
    listeners.forEach((fn) => fn());
  };

  return {
    listeners,
    subscribe(onChange: () => void) {
      listeners.add(onChange);
      return () => {
        listeners.delete(onChange);
      };
    },
    notify() {
      pending = true;
      if (timer != null) return;
      const wait = Math.max(0, ms - (performance.now() - lastAt));
      timer = setTimeout(flush, wait);
    },
    notifyNow() {
      if (timer != null) {
        clearTimeout(timer);
        timer = null;
      }
      pending = false;
      lastAt = 0;
      listeners.forEach((fn) => fn());
    },
  };
}
