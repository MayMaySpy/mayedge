import type { JournalTrip } from "@/lib/api";
import { DESK_DATE_LOCALE } from "@/lib/utcTime";
import { formatNumber, formatPrice, formatSigned, signClass } from "@/lib/utils";

/** Journal numbers come as full-precision decimal strings. These cut them to what a person reads. */

export const JOURNAL_RANGES = ["7d", "30d", "90d", "all"] as const;
export type JournalRange = (typeof JOURNAL_RANGES)[number];
/** "" is everything; "algos" is every algo family without manual. */
export const JOURNAL_ALGOS = ["", "algos", "manual", "planner", "chase", "grid", "ladder", "twap", "trail"] as const;
const ALGO_LABELS: Record<string, string> = { "": "All", algos: "All algos", manual: "Manual" };

export function algoLabel(value: string): string {
  return ALGO_LABELS[value] ?? value;
}

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

/** A trip or fill time, in UTC: the desk never uses local time. Column headers say UTC. */
export function when(ts: number): string {
  return new Date(seconds(ts) * 1000).toLocaleString(DESK_DATE_LOCALE, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "UTC",
  });
}

export function heldFor(open: number, close: number | null): string {
  const end = close == null ? Date.now() / 1000 : seconds(close);
  const sec = Math.max(0, Math.round(end - seconds(open)));
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))}m`;
  if (sec < 86_400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86_400)}d`;
}

/** A length of time from seconds, two units at most: 35m, 4h 12m, 2d 3h. */
export function duration(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  const min = Math.max(0, Math.round(n / 60));
  if (min < 60) return `${Math.max(1, min)}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return min % 60 ? `${h}h ${min % 60}m` : `${h}h`;
  return h % 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : `${Math.floor(h / 24)}d`;
}

/** A run of results: +3 is "3W", -2 is "2L". */
export function streak(value: number | null | undefined): string {
  if (!value) return "—";
  return value > 0 ? `${value}W` : `${-value}L`;
}

/** Basis points with a sign, one decimal: +12.3 bps. */
export function bps(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  const core = formatNumber(Math.abs(n), 1);
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${core} bps`;
}

/** Dollars with a sign, to the cent. */
export function money(value: string | null | undefined): string {
  return formatSigned(value, 2);
}

/** Dollars without a sign, to the cent. */
export function magnitude(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  return formatNumber(Math.abs(n), 2);
}

/** A 0–1 fraction as a whole percent. */
export function pct(fraction: string | null | undefined): string {
  const n = num(fraction);
  return n == null ? "—" : `${(n * 100).toFixed(0)}%`;
}

/** A value already in percent points, with a sign: +3.42%. Empty when absent. */
export function pctPoints(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "";
  const core = formatNumber(Math.abs(n), 2);
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${core}%`;
}

/** A plain ratio, two decimals: profit factor. */
export function ratio(value: string | null | undefined): string {
  const n = num(value);
  return n == null ? "—" : formatNumber(n, 2);
}

/** R multiples, two decimals with a sign: +1.25R. */
export function rValue(value: string | null | undefined): string {
  const n = num(value);
  if (n == null) return "—";
  const core = formatNumber(Math.abs(n), 2);
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${core}R`;
}

/** A price to about six significant digits: 3.17684, 2,412.18, 0.0000123456. */
export function price(value: string | null | undefined): string {
  return num(value) == null ? "—" : formatPrice(value);
}

/** A size, trailing zeros dropped, at most six decimals. */
export function size(value: string | null | undefined): string {
  const n = num(value);
  return n == null ? "—" : formatNumber(n, 0, 6);
}

export function pnlClass(value: string | null | undefined): string {
  return signClass(num(value));
}

export function inRange(trip: JournalTrip, range: JournalRange): boolean {
  if (trip.open) return true;
  const days = RANGE_DAYS[range];
  if (days == null || trip.close_ts == null) return days == null;
  return seconds(trip.close_ts) >= Date.now() / 1000 - days * 86_400;
}
