const EXPLORER = "https://app.lighter.xyz/explorer";

function accountIndex(value: number | string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(n) || n <= 0) return null;
  return n;
}

export function accountExplorerUrl(value: number | string | null | undefined): string | null {
  const index = accountIndex(value);
  if (index == null) return null;
  return `${EXPLORER}/accounts/${index}`;
}

export function logExplorerUrl(txHash: string | null | undefined): string | null {
  const hash = txHash?.trim() ?? "";
  if (!hash) return null;
  return `${EXPLORER}/logs/${hash}`;
}
