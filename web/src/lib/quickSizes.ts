import { useCallback, useSyncExternalStore } from "react";
import { parseDecimal } from "@/lib/numbers";

/** Single always-visible quick size (not a preset list). */
export const QUICK_SIZE_KEY = "mayedge-quick-size-v3";
const LEGACY_V2 = "mayedge-quick-sizes-v2";
const LEGACY_V1 = "mayedge-quick-sizes";
const EVENT = "mayedge-quick-size";

let cache: string | null = null;

function fromLegacyRows(raw: unknown): string {
  if (!Array.isArray(raw) || !raw.length) return "";
  const first = raw[0];
  if (first && typeof first === "object" && "qty" in first) {
    return String((first as { qty: unknown }).qty ?? "");
  }
  return "";
}

function read(): string {
  try {
    const v3 = localStorage.getItem(QUICK_SIZE_KEY);
    if (v3 != null) {
      cache = v3;
      return cache;
    }
    const v2 = localStorage.getItem(LEGACY_V2);
    if (v2) {
      cache = fromLegacyRows(JSON.parse(v2));
      localStorage.setItem(QUICK_SIZE_KEY, cache);
      return cache;
    }
    const v1 = localStorage.getItem(LEGACY_V1);
    if (v1) {
      cache = fromLegacyRows(JSON.parse(v1));
      localStorage.setItem(QUICK_SIZE_KEY, cache);
      return cache;
    }
    cache = "";
  } catch {
    cache = "";
  }
  return cache;
}

function emit() {
  window.dispatchEvent(new Event(EVENT));
}

export function getQuickSize(): string {
  return cache ?? read();
}

export function setQuickSize(qty: string) {
  const parsed = parseDecimal(qty);
  cache = parsed != null ? String(parsed) : qty.replace(/[^\d.,]/g, "");
  localStorage.setItem(QUICK_SIZE_KEY, cache);
  emit();
}

export function subscribeQuickSize(onChange: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key && e.key !== QUICK_SIZE_KEY) return;
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

export function useQuickSize() {
  const qty = useSyncExternalStore(subscribeQuickSize, getQuickSize, getQuickSize);
  const setQty = useCallback((next: string) => setQuickSize(next), []);
  return { qty, setQty };
}
