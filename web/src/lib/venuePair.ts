/** Desk is Lighter-only — show the symbol, not a venue prefix. */
export function pairLabel(symbol: string): string {
  return symbol;
}

export function liqIdentity(tradeId: string): string {
  return tradeId;
}
