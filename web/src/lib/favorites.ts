import { useCallback, useSyncExternalStore } from "react";
import { storedList } from "@/lib/storedList";

export const FAVORITES_KEY = "mayedge-favorites";
const list = storedList(FAVORITES_KEY, (raw) => raw as string[]);

export const getFavorites = list.get;
export const setFavorites = list.set;
export const subscribeFavorites = list.subscribe;

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

export function useFavorites() {
  const favorites = useSyncExternalStore(subscribeFavorites, getFavorites, getFavorites);
  const toggle = useCallback((symbol: string) => toggleFavorite(symbol), []);
  const reorder = useCallback((fromIndex: number, toIndex: number) => {
    reorderFavorites(fromIndex, toIndex);
  }, []);
  return [favorites, toggle, reorder] as const;
}
