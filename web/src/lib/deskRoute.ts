import { useCallback, useEffect, useState } from "react";

const SYMBOL_KEY = "mayedge-symbol";
export const DEFAULT_SYMBOL = "LIT";
const SYMBOL_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/;
const LEGACY_VENUE_RE = /^(lighter|hyperliquid)$/i;
const RESERVED = new Set(["API", "WS", "ASSETS"]);

export type ParsedPath = {
  symbol: string;
  /** When set, client should replaceState to this path (legacy /lighter/ETH → /ETH). */
  rewriteTo?: string;
};

export function parsePath(pathname: string): ParsedPath {
  const parts = pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  if (parts.length >= 2 && LEGACY_VENUE_RE.test(parts[0] ?? "")) {
    const sym = (parts[1] ?? "").toUpperCase();
    if (sym && SYMBOL_RE.test(sym)) {
      return { symbol: sym, rewriteTo: toPath(sym) };
    }
  }
  if (parts.length === 1) {
    const seg = parts[0] ?? "";
    if (seg && SYMBOL_RE.test(seg) && !LEGACY_VENUE_RE.test(seg)) {
      const upper = seg.toUpperCase();
      if (!RESERVED.has(upper)) return { symbol: upper };
    }
  }
  return { symbol: DEFAULT_SYMBOL };
}

export function toPath(symbol: string): string {
  return `/${symbol.toUpperCase()}`;
}

function readSymbolFromStorage(): string | null {
  try {
    return localStorage.getItem(SYMBOL_KEY);
  } catch {
    return null;
  }
}

export function readSymbol(pathname = typeof window !== "undefined" ? window.location.pathname : "/"): string {
  const parsed = parsePath(pathname);
  if (parsed.symbol !== DEFAULT_SYMBOL || pathname === "/" || pathname === "") {
    return parsed.symbol;
  }
  const stored = readSymbolFromStorage();
  if (stored && SYMBOL_RE.test(stored)) return stored.toUpperCase();
  return DEFAULT_SYMBOL;
}

function writePath(symbol: string, replace: boolean) {
  const path = toPath(symbol);
  if (typeof window === "undefined") return;
  if (window.location.pathname.toUpperCase() === path.toUpperCase()) return;
  const fn = replace ? window.history.replaceState : window.history.pushState;
  fn.call(window.history, { symbol }, "", path);
}

export function useDeskRoute() {
  const [symbol, setSymbolState] = useState(() => readSymbol());

  useEffect(() => {
    const parsed = parsePath(window.location.pathname);
    if (parsed.rewriteTo) {
      window.history.replaceState({ symbol: parsed.symbol }, "", parsed.rewriteTo);
    }
    writePath(symbol, true);
    try {
      localStorage.setItem(SYMBOL_KEY, symbol);
    } catch {
      /* ignore */
    }
    const onPop = () => setSymbolState(readSymbol());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setSymbol = useCallback((next: string) => {
    const sym = next.toUpperCase();
    setSymbolState(sym);
    try {
      localStorage.setItem(SYMBOL_KEY, sym);
    } catch {
      /* ignore */
    }
    writePath(sym, false);
  }, []);

  const setPair = useCallback((nextSymbol: string) => {
    setSymbol(nextSymbol);
  }, [setSymbol]);

  return { symbol, setSymbol, setPair } as const;
}

/** @deprecated use useDeskRoute */
export function useSymbolRoute() {
  const { symbol, setSymbol } = useDeskRoute();
  return [symbol, setSymbol] as const;
}
