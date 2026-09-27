import { useCallback, useSyncExternalStore } from "react";

const KEY = "mayedge-chart-quick";
const EVENT = "mayedge-chart-quick";

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

export function getQuickPanelOpen(): boolean {
  return cache ?? read();
}

export function setQuickPanelOpen(open: boolean) {
  cache = open;
  try {
    localStorage.setItem(KEY, open ? "1" : "0");
  } catch {
    /* ignore */
  }
  emit();
}

export function subscribeQuickPanel(onChange: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key && e.key !== KEY) return;
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

export function useQuickPanel() {
  const open = useSyncExternalStore(subscribeQuickPanel, getQuickPanelOpen, () => false);
  const setOpen = useCallback((next: boolean) => setQuickPanelOpen(next), []);
  return { open, setOpen };
}
