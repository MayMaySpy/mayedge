// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { JournalStats } from "@/components/journal/JournalParts";
import type { JournalSummaryGroup } from "@/lib/api";
import { duration, streak } from "@/lib/journalFormat";

afterEach(cleanup);

const STRIP: JournalSummaryGroup = {
  key: "all",
  count: 101,
  wins: 69,
  losses: 31,
  win_rate: "0.69",
  gross_pnl: "18.55",
  net: "16.24",
  fees: "0",
  funding: "-2.31",
  avg_win: "8.19",
  avg_loss: "-17.71",
  profit_factor: "1.03",
  expectancy: "0.16",
  largest_win: "96.81",
  largest_loss: "-138.11",
  maker_share: "0.25",
  avg_r: "-1.23",
  total_r: "-1.23",
  r_count: 1,
  max_drawdown: "180.82",
  curve: [],
  payoff_ratio: "0.4624",
  breakeven_win_rate: "0.6838",
  notional: "125000",
  net_bps: "1.3",
  recovery_factor: "0.09",
  max_win_streak: 9,
  max_loss_streak: 4,
  current_streak: -2,
  avg_hold_win_s: "1500",
  avg_hold_loss_s: "15120",
  long: { count: 60, win_rate: "0.7", net: "40.1" },
  short: { count: 41, win_rate: "0.66", net: "-23.86" },
  trading_days: 20,
  green_days: 12,
  best_day: "120.5",
  worst_day: "-150.2",
};

describe("JournalStats", () => {
  it("shows the desk row without R or fees", () => {
    render(<JournalStats strip={STRIP} />);
    expect(screen.getByText("Payoff")).toBeTruthy();
    expect(screen.getByText("needs 68%")).toBeTruthy();
    expect(screen.getByText("2L")).toBeTruthy();
    expect(screen.queryByText("Avg R")).toBeNull();
    expect(screen.queryByText("Fees")).toBeNull();
  });

  it("groups the page by edge, risk, wins and habits", () => {
    render(<JournalStats strip={STRIP} full />);
    for (const group of ["Edge", "Risk", "Wins", "Habits"]) expect(screen.getByText(group)).toBeTruthy();
    expect(screen.getByText("+1.3 bps")).toBeTruthy();
    expect(screen.getByText("12 of 20")).toBeTruthy();
    expect(screen.getByText("25m")).toBeTruthy();
    expect(screen.getByText("4h 12m")).toBeTruthy();
    expect(screen.getByText("60 · 70% win")).toBeTruthy();
    // R covers only Planner runs, and says how few.
    expect(screen.getByText("avg of 1 of 101 trips")).toBeTruthy();
  });

  it("leaves Planner R out when no trip has one", () => {
    render(<JournalStats strip={{ ...STRIP, r_count: 0, avg_r: null, total_r: null }} full />);
    expect(screen.queryByText("Planner R")).toBeNull();
  });
});

describe("journal formats", () => {
  it("reads durations and streaks", () => {
    expect([duration("30"), duration("2400"), duration("7200"), duration("97200"), duration(null)]).toEqual([
      "1m",
      "40m",
      "2h",
      "1d 3h",
      "—",
    ]);
    expect([streak(3), streak(-2), streak(0)]).toEqual(["3W", "2L", "—"]);
  });
});
