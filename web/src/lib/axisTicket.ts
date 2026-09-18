import { useCallback, useSyncExternalStore } from "react";

const KEY = "mayedge-chart-axis-ticket";
const EVENT = "mayedge-chart-axis-ticket";

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

export function getAxisTicketArmed(): boolean {
  return cache ?? read();
}

export function setAxisTicketArmed(armed: boolean) {
  cache = armed;
  try {
    localStorage.setItem(KEY, armed ? "1" : "0");
  } catch {
    /* ignore */
  }
  emit();
}

export function subscribeAxisTicket(onChange: () => void) {
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

export function useAxisTicket() {
  const armed = useSyncExternalStore(subscribeAxisTicket, getAxisTicketArmed, () => false);
  const setArmed = useCallback((next: boolean) => setAxisTicketArmed(next), []);
  return { armed, setArmed };
}
