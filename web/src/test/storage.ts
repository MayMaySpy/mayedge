/** In-memory Storage so tests never touch Node's file-backed localStorage. */

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

function install(name: "localStorage" | "sessionStorage") {
  const store = memoryStorage();
  Object.defineProperty(globalThis, name, { value: store, configurable: true, writable: true });
  if (typeof window !== "undefined") {
    Object.defineProperty(window, name, { value: store, configurable: true, writable: true });
  }
}

install("localStorage");
install("sessionStorage");
