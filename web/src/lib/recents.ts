import { useCallback, useSyncExternalStore } from "react";
import { storedList } from "@/lib/storedList";

export const RECENTS_KEY = "mayedge-recents";
export const RECENTS_MAX = 8;

export function nextRecents(cur: string[], symbol: string, max = RECENTS_MAX): string[] {
  const sym = symbol.trim().toUpperCase();
  if (!sym) return cur;
  return [sym, ...cur.filter((s) => s !== sym)].slice(0, max);
}

const list = storedList(RECENTS_KEY, (raw) => raw.map((s) => String(s).toUpperCase()).filter(Boolean));

export const getRecents = list.get;
export const setRecents = list.set;
export const subscribeRecents = list.subscribe;

export function pushRecent(symbol: string) {
  setRecents(nextRecents(getRecents(), symbol));
}

export function removeRecent(symbol: string) {
  setRecents(getRecents().filter((s) => s !== symbol.toUpperCase()));
}

export function useRecents() {
  const recents = useSyncExternalStore(subscribeRecents, getRecents, getRecents);
  const push = useCallback((symbol: string) => pushRecent(symbol), []);
  const remove = useCallback((symbol: string) => removeRecent(symbol), []);
  return [recents, push, remove] as const;
}
