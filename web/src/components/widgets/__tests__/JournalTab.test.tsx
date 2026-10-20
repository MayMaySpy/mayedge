// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JournalPage } from "@/components/JournalPage";
import { JournalTab } from "@/components/widgets/account/JournalTab";
import { api, type JournalSummaryGroup, type JournalTrip } from "@/lib/api";

vi.mock("@/lib/notify", () => ({
  notifyDesk: vi.fn(),
  notifyErr: vi.fn(),
  notifyOk: vi.fn(),
}));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  HistogramSeries: "Histogram",
  LineSeries: "Line",
  createChart: () => ({
    addSeries: () => ({ setData() {} }),
    timeScale: () => ({ fitContent() {} }),
    remove() {},
  }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const opened = Math.floor(Date.now() / 1000) - 3600;
const closed = opened + 3600;

const trip: JournalTrip = {
  trip_key: "1:a",
  market_index: 1,
  symbol: "ETH",
  side: "long",
  open_ts: opened,
  close_ts: closed,
  size: "1",
  avg_in: "100",
  avg_out: "120",
  net: "18",
  fees: "2",
  funding: "0",
  algo: "manual",
  r: null,
  partial: false,
  partial_reason: null,
  open: false,
  upnl: null,
  note: "",
  tags: [],
  fills: [
    {
      trade_id: "a",
      ts: opened,
      side: "buy",
      price: "100",
      size: "1",
      fee: "1",
      pnl: "0",
      is_maker: true,
      closing: false,
    },
    {
      trade_id: "b",
      ts: closed,
      side: "sell",
      price: "120",
      size: "1",
      fee: "1",
      pnl: "20",
      is_maker: false,
      closing: true,
    },
  ],
};

const strip: JournalSummaryGroup = {
  key: "all",
  count: 1,
  wins: 1,
  losses: 0,
  win_rate: "1",
  net: "18",
  fees: "2",
  funding: "0",
  profit_factor: null,
  expectancy: "18",
  avg_r: null,
  max_drawdown: "0",
  curve: [],
};

describe("JournalTab", () => {
  it("shows the summary and a trip, and expands its fills", async () => {
    vi.spyOn(api, "journalTrips").mockResolvedValue({ trips: [trip] });
    vi.spyOn(api, "journalSummary").mockImplementation(async (opts) => ({
      range: opts.range,
      group: opts.group,
      groups:
        opts.group === "day"
          ? [{ ...strip, key: "2023-11-14", net: "18" }]
          : [strip],
    }));

    render(<JournalTab active />);

    expect(await screen.findByText("ETH")).toBeTruthy();
    expect(screen.getAllByText("+18.00").length).toBeGreaterThan(0);
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.queryByText("close")).toBeNull();

    await userEvent.click(screen.getByText("ETH"));
    expect(screen.getByText("close")).toBeTruthy();
    expect(screen.getByText("buy")).toBeTruthy();
    expect(screen.getByText("sell")).toBeTruthy();
  });
});

describe("JournalPage", () => {
  it("shows the full summary and the breakdowns by market and algo", async () => {
    vi.spyOn(api, "journalTrips").mockResolvedValue({ trips: [trip] });
    const summary = vi.spyOn(api, "journalSummary").mockImplementation(async (opts) => ({
      range: opts.range,
      group: opts.group,
      groups:
        opts.group === "market"
          ? [{ ...strip, key: "ETH" }]
          : opts.group === "algo"
            ? [{ ...strip, key: "manual" }]
            : [{ ...strip, profit_factor: "1.041666974894288296626184072", largest_win: "18" }],
    }));

    render(<JournalPage />);

    expect(await screen.findByText("By market")).toBeTruthy();
    expect(screen.getByText("By algo")).toBeTruthy();
    const byAlgo = screen.getByText("By algo").closest("section") as HTMLElement;
    expect(await within(byAlgo).findByText("manual")).toBeTruthy();
    expect(within(byAlgo).getByText("All")).toBeTruthy();
    const options = [...(screen.getByLabelText("Algo") as HTMLSelectElement).options].map((o) => o.text);
    expect(options.slice(0, 3)).toEqual(["All", "All algos", "Manual"]);
    expect(screen.getByText("Largest win")).toBeTruthy();
    expect(screen.queryByText(/1\.0416669/)).toBeNull();
    expect(summary.mock.calls.map(([opts]) => opts.group).sort()).toEqual(["algo", "day", "market", "none"]);
  });
});
