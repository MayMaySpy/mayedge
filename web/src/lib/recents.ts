import { useCallback, useSyncExternalStore } from "react";

export const RECENTS_KEY = "mayedge-recents";
const EVENT = "mayedge-recents";
export const RECENTS_MAX = 8;

let cache: string[] | null = null;

export function nextRecents(cur: string[], symbol: string, max = RECENTS_MAX): string[] {
  const sym = symbol.trim().toUpperCase();
  if (!sym) return cur;
  return [sym, ...cur.filter((s) => s !== sym)].slice(0, max);
}

function read(): string[] {
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    const next = raw ? (JSON.parse(raw) as string[]) : [];
    cache = Array.isArray(next) ? next.map((s) => String(s).toUpperCase()).filter(Boolean) : [];
  } catch {
    cache = [];
  }
  return cache;
}

function emit() {
  window.dispatchEvent(new Event(EVENT));
}

export function getRecents() {
  return cache ?? read();
}

export function setRecents(next: string[]) {
  cache = next;
  localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
  emit();
}

export function pushRecent(symbol: string) {
  setRecents(nextRecents(getRecents(), symbol));
}

export function removeRecent(symbol: string) {
  setRecents(getRecents().filter((s) => s !== symbol.toUpperCase()));
}

export function subscribeRecents(onChange: () => void) {
  const handler = () => {
    cache = null;
    onChange();
  };
  window.addEventListener(EVENT, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}

export function useRecents() {
  const recents = useSyncExternalStore(subscribeRecents, getRecents, getRecents);
  const push = useCallback((symbol: string) => pushRecent(symbol), []);
  const remove = useCallback((symbol: string) => removeRecent(symbol), []);
  return [recents, push, remove] as const;
}
