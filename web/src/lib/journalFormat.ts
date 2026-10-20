import type { JournalTrip } from "@/lib/api";
import { formatSigned } from "@/lib/utils";

/** Journal numbers come as full-precision decimal strings. These cut them to what a person reads. */

export const JOURNAL_RANGES = ["7d", "30d", "90d", "all"] as const;
export type JournalRange = (typeof JOURNAL_RANGES)[number];
export const JOURNAL_ALGOS = ["", "planner", "chase", "grid", "ladder", "twap", "trail", "manual"] as const;

const RANGE_DAYS: Record<JournalRange, number | null> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  all: null,
};

function num(value: string | number | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function seconds(ts: number): number {
  return ts > 1e12 ? ts / 1000 : ts;
}

export function when(ts: number): string {
  return new Date(seconds(ts) * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function heldFor(open: number, close: number | null): string {
  const end = close == null ? Date.now() / 1000 : seconds(close);
  const sec = Math.max(0, Math.round(end - seconds(open)));
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))}m`;
  if (sec < 86_400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86_400)}d`;
}

/** Dollars with a sign, to the cent. */
export function money(value: string | null | undefined): string {
  return formatSigned(value, 2);
}

/** Dollars without a sign, to the cent. */
export function magnitude(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  return Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A 0–1 fraction as a whole percent. */
export function pct(fraction: string | null | undefined): string {
  const n = num(fraction);
  return n == null ? "—" : `${(n * 100).toFixed(0)}%`;
}

/** A plain ratio, two decimals: profit factor. */
export function ratio(value: string | null | undefined): string {
  const n = num(value);
  return n == null ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** R multiples, two decimals with a sign: +1.25R. */
export function rValue(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  const core = Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${core}R`;
}

/** A price to about six significant digits: 3.17684, 2,412.18, 0.0000123456. */
export function price(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  const abs = Math.abs(n);
  // Above 1, digits before the point eat into the six. Below 1, leading zeros do not.
  const decimals =
    abs >= 1
      ? Math.max(2, 6 - (Math.floor(Math.log10(abs)) + 1))
      : abs > 0
        ? Math.min(10, 5 - Math.floor(Math.log10(abs)))
        : 2;
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: decimals });
}

/** A size, trailing zeros dropped, at most six decimals. */
export function size(value: string | null | undefined): string {
  const n = num(value);
  return n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

export function pnlClass(value: string | null | undefined): string {
  const n = num(value) ?? 0;
  if (n > 0) return "text-bid";
  if (n < 0) return "text-ask";
  return "text-muted-foreground";
}

export function inRange(trip: JournalTrip, range: JournalRange): boolean {
  if (trip.open) return true;
  const days = RANGE_DAYS[range];
  if (days == null || trip.close_ts == null) return days == null;
  return seconds(trip.close_ts) >= Date.now() / 1000 - days * 86_400;
}
