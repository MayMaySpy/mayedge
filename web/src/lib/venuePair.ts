/** LIT-BTC */
export function pairLabel(symbol: string): string {
  return `LIT-${symbol}`;
}

export function liqIdentity(tradeId: string): string {
  return tradeId;
}
