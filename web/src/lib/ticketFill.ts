import { useSyncExternalStore } from "react";

export type LimitPricePick = { price: string; seq: number };

let pick: LimitPricePick | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

export function pickLimitPrice(price: string) {
  const raw = price.trim();
  if (!raw) return;
  pick = { price: raw, seq: (pick?.seq ?? 0) + 1 };
  emit();
}

export function resetLimitPricePick() {
  pick = null;
  emit();
}

export function getLimitPricePick(): LimitPricePick | null {
  return pick;
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

export function useLimitPricePick(): LimitPricePick | null {
  return useSyncExternalStore(subscribe, getLimitPricePick, () => null);
}
