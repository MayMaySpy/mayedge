import type { Market } from "@/lib/api";
import { formatPrice, formatSize } from "@/lib/utils";

/**
 * Each market's venue precision, by symbol: Lighter fixes `price_decimals` (the tick) and
 * `size_decimals` (the lot) per market, not a count of significant digits. PUMP prices
 * to 6 decimals, BTC to 1. A perp wins over a spot market of the same symbol.
 */
type Decimals = { price: number; size: number };

let bySymbol = new Map<string, Decimals>();

export function setMarketDecimals(markets: Market[]): void {
  const next = new Map<string, Decimals>();
  for (const m of markets) {
    if (m.price_decimals == null || (next.has(m.symbol) && !m.is_perp)) continue;
    next.set(m.symbol, { price: m.price_decimals, size: m.size_decimals ?? 6 });
  }
  bySymbol = next;
}

export function marketDecimals(symbol: string | null | undefined): Decimals | undefined {
  return symbol ? bySymbol.get(symbol) : undefined;
}

/** A price at its market's tick: PUMP 0.004813, BTC 82,759.4. Unknown market: ~6 significant digits. */
export function marketPrice(value: string | number | null | undefined, symbol: string | null | undefined): string {
  return formatPrice(value, marketDecimals(symbol)?.price);
}

/** A size to at most its market's lot decimals, trailing zeros dropped. */
export function marketSize(value: string | number | null | undefined, symbol: string | null | undefined): string {
  return formatSize(value, marketDecimals(symbol)?.size);
}
