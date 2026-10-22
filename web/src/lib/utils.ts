import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * The desk's one number format, whatever the browser's locale: `.` decimals and `,` thousands,
 * as the venue and the chart axis print them. Every number on the desk goes through this.
 */
export const DESK_LOCALE = "en-US";
const numberFormats = new Map<string, Intl.NumberFormat>();

/** `n` with between `min` and `max` fraction digits: formatNumber(1363.16, 2) is "1,363.16". */
export function formatNumber(n: number, min = 0, max = min): string {
  const lo = Math.max(0, Math.min(20, Math.floor(min)));
  const hi = Math.max(lo, Math.min(20, Math.floor(max)));
  const key = `${lo}:${hi}`;
  let fmt = numberFormats.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat(DESK_LOCALE, { minimumFractionDigits: lo, maximumFractionDigits: hi });
    numberFormats.set(key, fmt);
  }
  return fmt.format(n);
}

/** Dollars with the `$` in front and the sign before it: $1,363.16, -$4.20. */
export function formatUsd(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value < 0 ? "-" : ""}$${formatNumber(Math.abs(value), digits)}`;
}

/**
 * A price. With `decimals` (a market's tick) it shows exactly that many: 0.004813, 82,759.4.
 * Without, about six significant digits: 3.17684, 2,412.18, 0.0000123456.
 */
export function formatPrice(value: string | number | null | undefined, decimals?: number): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return String(value);
  if (decimals != null && Number.isFinite(decimals)) {
    const fixed = Math.max(0, Math.min(20, Math.floor(decimals)));
    return formatNumber(n, fixed);
  }
  const abs = Math.abs(n);
  // Above 1, digits before the point eat into the six. Below 1, leading zeros do not.
  const max =
    abs >= 1
      ? Math.max(2, 6 - (Math.floor(Math.log10(abs)) + 1))
      : abs > 0
        ? Math.min(10, 5 - Math.floor(Math.log10(abs)))
        : 2;
  return formatNumber(n, 2, max);
}

/** A size to at most `decimals` (a market's lot decimals), trailing zeros dropped. */
export function formatSize(value: string | number | null | undefined, decimals = 6): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return String(value);
  return formatNumber(n, 0, decimals);
}

export function formatUsdCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value <= 0) return "";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}k`;
  return `$${value.toFixed(0)}`;
}

/** Green for a gain, red for a loss, muted for flat or unknown. */
export function signClass(value: number | null | undefined): string {
  if (value != null && value > 0) return "text-bid";
  if (value != null && value < 0) return "text-ask";
  return "text-muted-foreground";
}

export function formatSigned(value: string | number | null | undefined, decimals = 2): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "—";
  const core = formatNumber(Math.abs(n), 2, decimals);
  if (n > 0) return `+${core}`;
  if (n < 0) return `-${core}`;
  return core;
}

export function formatPct(value: number | null | undefined, digits?: number): string {
  if (value == null || Number.isNaN(value)) return "—";
  const d = digits ?? (Math.abs(value) < 0.01 ? 3 : 2);
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, d)}%`;
}

/** Unsigned percent for parentheticals: `+2.90 (1.5%)`. */
export function formatPctAbs(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "—";
  return `${formatNumber(Math.abs(value), digits)}%`;
}

export function formatApr(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, digits)}%`;
}
