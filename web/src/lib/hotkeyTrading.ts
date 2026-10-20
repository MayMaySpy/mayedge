import { useCallback, useSyncExternalStore } from "react";

const KEY = "mayedge-hotkey-trading";
const EVENT = "mayedge-hotkey-trading";

let cache: boolean | null = null;

function read(): boolean {
  if (cache != null) return cache;
  try {
    cache = localStorage.getItem(KEY) === "1";
  } catch {
    cache = false;
  }
  return cache;
}

function emit() {
  window.dispatchEvent(new Event(EVENT));
}

export function getHotkeyTrading(): boolean {
  return cache ?? read();
}

export function setHotkeyTrading(armed: boolean) {
  cache = armed;
  try {
    localStorage.setItem(KEY, armed ? "1" : "0");
  } catch {
    /* ignore */
  }
  emit();
}

export function subscribeHotkeyTrading(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key && event.key !== KEY) return;
    cache = null;
    onChange();
  };
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useHotkeyTrading() {
  const armed = useSyncExternalStore(subscribeHotkeyTrading, getHotkeyTrading, () => false);
  const setArmed = useCallback((next: boolean) => setHotkeyTrading(next), []);
  return { armed, setArmed };
}
