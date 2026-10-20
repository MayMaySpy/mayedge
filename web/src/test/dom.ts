/** Browser APIs jsdom lacks and the desk's Radix primitives call. Import first in a component test. */

class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const g = globalThis as Record<string, unknown>;
g.ResizeObserver ??= NoopObserver;
g.IntersectionObserver ??= NoopObserver;

if (typeof window !== "undefined") {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  const proto = window.Element.prototype;
  proto.scrollIntoView ??= () => {};
  proto.hasPointerCapture ??= () => false;
  proto.setPointerCapture ??= () => {};
  proto.releasePointerCapture ??= () => {};
}

// Newer Node ships its own `localStorage` that is undefined without a backing file, and it
// shadows jsdom's. Give the desk an in-memory one so saved preferences behave as in a browser.
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

for (const name of ["localStorage", "sessionStorage"] as const) {
  const store = memoryStorage();
  Object.defineProperty(globalThis, name, { value: store, configurable: true, writable: true });
  if (typeof window !== "undefined") {
    Object.defineProperty(window, name, { value: store, configurable: true, writable: true });
  }
}
