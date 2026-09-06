import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPrice(value: string | number | null | undefined, decimals = 4): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return String(value);
  const max = Math.max(0, Math.min(20, Math.floor(Number.isFinite(decimals) ? decimals : 4)));
  const min = Math.min(2, max);
  return n.toLocaleString(undefined, {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });
}

export function formatSize(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
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
  return `${sign}${value.toFixed(d)}%`;
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
