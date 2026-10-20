import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
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
    return n.toLocaleString(undefined, { minimumFractionDigits: fixed, maximumFractionDigits: fixed });
  }
  const abs = Math.abs(n);
  // Above 1, digits before the point eat into the six. Below 1, leading zeros do not.
  const max =
    abs >= 1
      ? Math.max(2, 6 - (Math.floor(Math.log10(abs)) + 1))
      : abs > 0
        ? Math.min(10, 5 - Math.floor(Math.log10(abs)))
        : 2;
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: max });
}

/** A size to at most `decimals` (a market's lot decimals), trailing zeros dropped. */
export function formatSize(value: string | number | null | undefined, decimals = 6): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString(undefined, { maximumFractionDigits: Math.max(0, Math.min(20, Math.floor(decimals))) });
}

export function formatUsdCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value <= 0) return "";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}k`;
  return `$${value.toFixed(0)}`;
}

export function formatSigned(value: string | number | null | undefined, decimals = 2): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "—";
  const core = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: decimals,
  });
  if (n > 0) return `+${core}`;
  if (n < 0) return `-${core}`;
  return core;
}

export function formatPct(value: number | null | undefined, digits?: number): string {
  if (value == null || Number.isNaN(value)) return "—";
  const d = digits ?? (Math.abs(value) < 0.01 ? 3 : 2);
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })}%`;
}

/** Unsigned percent for parentheticals: `+2,90 (1,5%)`. */
export function formatPctAbs(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "—";
  return `${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

export function formatApr(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}%`;
}
