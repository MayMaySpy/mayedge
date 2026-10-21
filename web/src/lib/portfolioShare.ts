import type { PortfolioDay, PortfolioHistory, PortfolioKind } from "@/lib/api";
import { PORTFOLIO_KINDS } from "@/lib/portfolioDay";
import { formatNumber } from "@/lib/utils";

/** Pure helpers behind the Portfolio's day pages, CSV, calendar and PnL card (docs/portfolio-rules.md W7–W9). */

const DAY_MS = 86_400_000;

function num(value: string | null | undefined): number {
  const n = Number(value ?? "0");
  return Number.isFinite(n) ? n : 0;
}

/** W7: one page of rows, newest first. `page` is clamped to the last page. */
export function pageOf<T>(rows: T[], page: number, size: number): { rows: T[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const at = Math.min(Math.max(0, page), pages - 1);
  return { rows: rows.slice(at * size, at * size + size), page: at, pages };
}

/** W7: every day in the range, oldest first, each kind as the venue's full decimal. */
export function daysCsv(days: PortfolioDay[], kinds: readonly PortfolioKind[] = PORTFOLIO_KINDS): string {
  const lines = [["day_utc", ...kinds, "total"].join(",")];
  for (const day of days) {
    lines.push([day.day, ...kinds.map((k) => day.kinds[k] ?? ""), day.total ?? ""].join(","));
  }
  return `${lines.join("\n")}\n`;
}

export type CalendarCell = { day: string; date: number; total: number | null } | null;
export type CalendarWeek = { cells: CalendarCell[]; total: number | null };

/** W8: rows the calendar always draws, so paging months never changes its height. */
export const CALENDAR_WEEKS = 6;

/**
 * W8: one UTC month as six weeks of seven days, Monday first. A day without a row has a
 * null total; a week past the month's end is all blank cells.
 */
export function calendarMonth(days: PortfolioDay[], year: number, month: number): CalendarWeek[] {
  const byDay = new Map(days.map((d) => [d.day, d]));
  const first = Date.UTC(year, month, 1);
  const count = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const lead = (new Date(first).getUTCDay() + 6) % 7;
  const cells: CalendarCell[] = Array.from({ length: lead }, () => null);
  for (let date = 1; date <= count; date++) {
    const day = new Date(first + (date - 1) * DAY_MS).toISOString().slice(0, 10);
    const row = byDay.get(day);
    cells.push({ day, date, total: row?.total != null ? num(row.total) : null });
  }
  while (cells.length < CALENDAR_WEEKS * 7) cells.push(null);
  const weeks: CalendarWeek[] = [];
  for (let i = 0; i < cells.length; i += 7) {
    const week = cells.slice(i, i + 7);
    const known = week.filter((c) => c?.total != null);
    weeks.push({ cells: week, total: known.length ? known.reduce((s, c) => s + (c?.total ?? 0), 0) : null });
  }
  return weeks;
}

/** The value at or before `ts`, else the first one after it. */
function valueAt(points: PortfolioHistory["points"], ts: number): number {
  let found: number | null = null;
  for (const p of points) {
    if (p.ts > ts) break;
    found = num(p.total);
  }
  return found ?? num(points[0]?.total);
}

/**
 * W9: a range's change and return. The change is the sum of its Day changes (Flows
 * left out, H6). The return compounds each day's change over that day's opening value,
 * so a deposit grows the base from its day on instead of reading as a gain.
 */
export function periodReturn(
  days: PortfolioDay[],
  points: PortfolioHistory["points"],
): { change: number; pct: number | null } {
  let change = 0;
  let growth = 1;
  let counted = false;
  for (const day of days) {
    const total = num(day.total);
    change += total;
    const base = valueAt(points, day.start);
    if (base > 0) {
      growth *= 1 + total / base;
      counted = true;
    }
  }
  return { change, pct: counted ? (growth - 1) * 100 : null };
}

/**
 * W9: the card's curve, the running PnL since `since`: the total value's move less every
 * Flow after the first point, so a deposit or a move between kinds is not a jump.
 */
export function pnlCurve(history: PortfolioHistory, since: number): { ts: number; pnl: number }[] {
  const points = history.points.filter((p) => p.ts >= since);
  if (points.length === 0) return [];
  const start = num(points[0].total);
  const flows = [...history.flows].sort((a, b) => a.ts - b.ts);
  return points.map((p) => {
    const moved = flows
      .filter((f) => f.ts > points[0].ts && f.ts <= p.ts)
      .reduce((s, f) => s + num(f.amount), 0);
    return { ts: p.ts, pnl: num(p.total) - start - moved };
  });
}

/** A signed amount short enough for a calendar cell: +27, -4.20, +1.2k. */
export function cellMoney(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const fixed = (n: number, digits: number) => formatNumber(n, digits);
  if (abs >= 10_000) return `${sign}${fixed(abs / 1000, 0)}k`;
  if (abs >= 1000) return `${sign}${fixed(abs / 1000, 1)}k`;
  if (abs >= 10) return `${sign}${fixed(abs, 0)}`;
  return `${sign}${fixed(abs, 2)}`;
}

/** Saves `text` as a file named `name`. */
export function downloadText(name: string, text: string, type = "text/csv"): void {
  downloadBlob(name, new Blob([text], { type }));
}

export function downloadBlob(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
