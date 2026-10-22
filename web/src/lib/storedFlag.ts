import { useCallback, useSyncExternalStore } from "react";

/** An on/off setting kept in this browser. Every component and tab that reads it sees a change. */
export function storedFlag(key: string) {
  let cache: boolean | null = null;

  function read(): boolean {
    if (cache != null) return cache;
    try {
      cache = localStorage.getItem(key) === "1";
    } catch {
      cache = false;
    }
    return cache;
  }

  function get(): boolean {
    return cache ?? read();
  }

  function set(on: boolean) {
    cache = on;
    try {
      localStorage.setItem(key, on ? "1" : "0");
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(key));
  }

  function subscribe(onChange: () => void) {
    const onStorage = (e: StorageEvent) => {
      if (e.key && e.key !== key) return;
      cache = null;
      onChange();
    };
    window.addEventListener(key, onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(key, onChange);
      window.removeEventListener("storage", onStorage);
    };
  }

  function useFlag(): [boolean, (on: boolean) => void] {
    const on = useSyncExternalStore(subscribe, get, () => false);
    const setOn = useCallback((next: boolean) => set(next), []);
    return [on, setOn];
  }

  return { get, set, subscribe, useFlag };
}
