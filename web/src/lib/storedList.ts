/** A list of symbols kept in this browser. Every component and tab that reads it sees a change. */
export function storedList(key: string, clean: (raw: unknown[]) => string[] = (raw) => raw.map(String)) {
  let cache: string[] | null = null;

  function read(): string[] {
    try {
      const raw = localStorage.getItem(key);
      const next: unknown = raw ? JSON.parse(raw) : [];
      cache = Array.isArray(next) ? clean(next) : [];
    } catch {
      cache = [];
    }
    return cache;
  }

  function get(): string[] {
    return cache ?? read();
  }

  function set(next: string[]) {
    cache = next;
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(key));
  }

  function subscribe(onChange: () => void) {
    const handler = () => {
      cache = null;
      onChange();
    };
    window.addEventListener(key, handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener(key, handler);
      window.removeEventListener("storage", handler);
    };
  }

  return { get, set, subscribe };
}
