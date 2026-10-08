import type { LiquidationSummaryHours } from "@/lib/api";

const KEY = "mayedge-scan-liq-hours";

export const LIQ_HOURS = [
  { value: 1, label: "1h" },
  { value: 4, label: "4h" },
  { value: 24, label: "24h" },
  { value: 168, label: "7d" },
  { value: 720, label: "30d" },
] as const satisfies readonly { value: LiquidationSummaryHours; label: string }[];

function isLiqHour(n: number): n is LiquidationSummaryHours {
  return LIQ_HOURS.some((h) => h.value === n);
}

export function loadLiqHours(fallback: LiquidationSummaryHours): LiquidationSummaryHours {
  try {
    const n = parseInt(localStorage.getItem(KEY) ?? "", 10);
    if (isLiqHour(n)) return n;
  } catch {
    /* ignore */
  }
  return fallback;
}

export function persistLiqHours(hours: LiquidationSummaryHours): void {
  try {
    localStorage.setItem(KEY, String(hours));
  } catch {
    /* ignore */
  }
}
