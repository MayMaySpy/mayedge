import { describe, expect, it } from "vitest";
import type { PortfolioDay, PortfolioHistory } from "@/lib/api";
import { calendarMonth, cellMoney, daysCsv, pageOf, periodReturn, pnlCurve } from "@/lib/portfolioShare";

const DAY = 86_400_000;
const OCT_1 = Date.UTC(2026, 9, 1);

const day = (date: number, total: string, perps = total): PortfolioDay => ({
  day: new Date(OCT_1 + (date - 1) * DAY).toISOString().slice(0, 10),
  start: OCT_1 + (date - 1) * DAY,
  kinds: { perps, spot: "0", llp: "0", staking: "0" },
  total,
});

const point = (ts: number, total: string) => ({ ts, total, perps: total, spot: "0", llp: "0", staking: "0" });

describe("portfolio day pages and CSV", () => {
  it("pages newest-first rows and clamps past the last page", () => {
    const rows = Array.from({ length: 45 }, (_, i) => i);
    expect(pageOf(rows, 0, 20)).toEqual({ rows: rows.slice(0, 20), page: 0, pages: 3 });
    expect(pageOf(rows, 2, 20).rows).toEqual([40, 41, 42, 43, 44]);
    expect(pageOf(rows, 9, 20).page).toBe(2);
    expect(pageOf([], 0, 20)).toEqual({ rows: [], page: 0, pages: 1 });
  });

  it("writes every day, each kind at full precision", () => {
    expect(daysCsv([day(19, "161.801234", "6.54")])).toBe(
      "day_utc,perps,spot,llp,staking,total\n2026-10-19,6.54,0,0,0,161.801234\n",
    );
  });
});

describe("PnL calendar", () => {
  it("lays a UTC month out Monday first, with week totals", () => {
    // 2026-10-01 is a Thursday: three blank cells lead.
    const weeks = calendarMonth([day(1, "10"), day(2, "-4"), day(5, "3")], 2026, 9);
    expect(weeks[0].cells.slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0].cells[3]).toEqual({ day: "2026-10-01", date: 1, total: 10 });
    expect(weeks[0].total).toBe(6);
    expect(weeks[1].cells[0]).toEqual({ day: "2026-10-05", date: 5, total: 3 });
    expect(weeks[1].cells[1]?.total).toBeNull();
    expect(weeks.every((w) => w.cells.length === 7)).toBe(true);
    // Always six rows: a four-week February draws as tall as a six-week month.
    expect(weeks).toHaveLength(6);
    expect(calendarMonth([], 2027, 1)).toHaveLength(6);
    expect(weeks[5].total).toBeNull();
    expect(weeks.flatMap((w) => w.cells).filter(Boolean)).toHaveLength(31);
  });

  it("keeps a cell's amount short", () => {
    const two = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2 });
    const one = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 1 });
    expect([cellMoney(27.94), cellMoney(-4.2), cellMoney(1234), cellMoney(-15_600), cellMoney(0)]).toEqual([
      "+28",
      `-${two(4.2)}`,
      `+${one(1.2)}k`,
      "-16k",
      two(0),
    ]);
  });
});

describe("PnL card numbers", () => {
  it("compounds each day over its own opening value, so a deposit is not a gain", () => {
    // Day 1: +10 on 1000. Then 1000 is deposited. Day 2: +20 on 2010.
    const days = [day(1, "10"), day(2, "20")];
    const points = [point(OCT_1, "1000"), point(OCT_1 + DAY, "2010"), point(OCT_1 + 2 * DAY, "2030")];
    const { change, pct } = periodReturn(days, points);
    expect(change).toBe(30);
    expect(pct).toBeCloseTo((1.01 * (1 + 20 / 2010) - 1) * 100, 6);
    expect(periodReturn(days, []).pct).toBeNull();
  });

  it("draws running PnL, taking every Flow out of the value's move", () => {
    const history: PortfolioHistory = {
      range: "7d",
      resolution: "1h",
      points: [point(OCT_1, "1000"), point(OCT_1 + DAY, "1510"), point(OCT_1 + 2 * DAY, "1505")],
      flows: [{ ts: OCT_1 + DAY, kind: "perps", amount: "500" }],
    };
    expect(pnlCurve(history, OCT_1).map((p) => p.pnl)).toEqual([0, 10, 5]);
    expect(pnlCurve(history, OCT_1 + DAY).map((p) => p.pnl)).toEqual([0, -5]);
  });
});
