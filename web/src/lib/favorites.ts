import { useCallback, useSyncExternalStore } from "react";

export const FAVORITES_KEY = "mayedge-favorites";
const EVENT = "mayedge-favorites";

let cache: string[] | null = null;

function read(): string[] {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    const next = raw ? (JSON.parse(raw) as string[]) : [];
    cache = Array.isArray(next) ? next : [];
  } catch {
    cache = [];
  }
  return cache;
}

function emit() {
  window.dispatchEvent(new Event(EVENT));
}

export function getFavorites() {
  return cache ?? read();
}

export function setFavorites(next: string[]) {
  cache = next;
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(next));
  emit();
}

export function toggleFavorite(symbol: string) {
  const cur = getFavorites();
  setFavorites(cur.includes(symbol) ? cur.filter((s) => s !== symbol) : [symbol, ...cur]);
}

export function reorderFavorites(fromIndex: number, toIndex: number) {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
  const cur = [...getFavorites()];
  if (fromIndex >= cur.length || toIndex >= cur.length) return;
  const [item] = cur.splice(fromIndex, 1);
  cur.splice(toIndex, 0, item);
  setFavorites(cur);
}

export function subscribeFavorites(onChange: () => void) {
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

export function useFavorites() {
  const favorites = useSyncExternalStore(subscribeFavorites, getFavorites, getFavorites);
  const toggle = useCallback((symbol: string) => toggleFavorite(symbol), []);
  const reorder = useCallback((fromIndex: number, toIndex: number) => {
    reorderFavorites(fromIndex, toIndex);
  }, []);
  return [favorites, toggle, reorder] as const;
}
