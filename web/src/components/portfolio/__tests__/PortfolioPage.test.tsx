// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PortfolioPage } from "@/components/PortfolioPage";
import { api, type PortfolioHistory, type PortfolioNow } from "@/lib/api";
import { heldKinds, historyKinds } from "@/lib/portfolioDay";

vi.mock("@/lib/notify", () => ({ notifyErr: vi.fn(), notifyOk: vi.fn() }));

const markers = vi.fn();
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  HistogramSeries: "Histogram",
  LineSeries: "Line",
  createSeriesMarkers: (...args: unknown[]) => markers(...args),
  createChart: () => ({
    addSeries: () => ({ setData() {} }),
    timeScale: () => ({ fitContent() {} }),
    subscribeCrosshairMove() {},
    unsubscribeCrosshairMove() {},
    remove() {},
  }),
}));

const kind = (value: string, change: string, flows = "0") => ({
  value,
  value_at_open: value,
  change,
  change_pct: null,
  flows,
});

const NOW: PortfolioNow = {
  ts: 2,
  open: 1,
  total: { value: "5681.19", value_at_open: "5493.28", change: "187.88", change_pct: "3.42", flows: "0" },
  kinds: {
    perps: kind("1221", "27.94"),
    spot: kind("1218.25", "16.89"),
    llp: kind("0", "0"),
    staking: kind("3241.94", "143.04"),
  },
  mismatch: [],
  spot: [{ symbol: "ETH", qty: "0.50000082", price: "2436.49", value: "1218.25", upnl: "249.41" }],
  pools: [
    {
      pool: 281474976624800,
      kind: "staking",
      shares: "96814113",
      units: "1018.2101",
      unit: "LIT",
      value: "3241.88",
      apy: "27.588",
      principal: "998.9623",
    },
  ],
  unlocks: [],
};

const HISTORY: PortfolioHistory = {
  range: "30d",
  resolution: "1d",
  points: [
    { ts: 1_792_000_000_000, perps: "700", spot: "2600", llp: "500", staking: "5100", total: "8900" },
    { ts: 1_792_086_400_000, perps: "1239", spot: "2600", llp: "0", staking: "5100", total: "8939" },
  ],
  flows: [
    { ts: 1_792_086_400_000, kind: "perps", amount: "539.41" },
    { ts: 1_792_086_400_000, kind: "llp", amount: "-539.41" },
  ],
};

beforeEach(() => {
  markers.mockClear();
  vi.spyOn(api, "portfolio").mockResolvedValue(NOW);
  vi.spyOn(api, "portfolioHistory").mockResolvedValue(HISTORY);
  vi.spyOn(api, "portfolioDays").mockResolvedValue({
    range: "30d",
    days: [
      {
        day: "2026-10-19",
        start: 1,
        kinds: { perps: "6.54", spot: "15.91", llp: "0", staking: "139.35" },
        total: "161.80",
      },
      { day: "2026-10-10", start: 0, kinds: { perps: "1", spot: "2", llp: "0", staking: "3" }, total: "6" },
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PortfolioPage", () => {
  it("leads with the total and today's change since 00:00 UTC", async () => {
    render(<PortfolioPage />);
    expect(await screen.findByText("$5,681.19")).toBeTruthy();
    expect(screen.getByText("+187.88")).toBeTruthy();
    expect(screen.getByText("Today, since 00:00 UTC")).toBeTruthy();
    const [open, detail] = vi.mocked(api.portfolio).mock.calls[0];
    expect(open).toBe(Date.now() - (Date.now() % 86_400_000));
    expect(detail).toBeUndefined();
    expect(vi.mocked(api.portfolioDays).mock.calls[0]).toEqual(["30d"]);
  });

  it("switches to the last 24 hours", async () => {
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    await userEvent.click(screen.getByRole("radio", { name: "24h" }));
    const open = vi.mocked(api.portfolio).mock.calls.at(-1)?.[0] ?? 0;
    expect(Math.abs(Date.now() - 86_400_000 - open)).toBeLessThan(5_000);
    expect(await screen.findByText("Last 24h")).toBeTruthy();
  });

  it("charts a kind held earlier in the range, and marks each Flow on its kind", async () => {
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    // LLP holds nothing now but did in the range: it keeps a column and a line.
    const days = screen.getByText("2026-10-19").closest("table") as HTMLElement;
    expect(within(days).getByText("LLP")).toBeTruthy();
    expect(markers).toHaveBeenCalledTimes(2);
    expect(within(days).getByText("Day (UTC)")).toBeTruthy();
  });

  it("lists what each Holding is made of", async () => {
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    expect(screen.getByText("ETH")).toBeTruthy();
    expect(screen.getByText("1,018.21 LIT")).toBeTruthy();
    expect(screen.getByText("27.59%")).toBeTruthy();
    expect(screen.getByText("Not in LLP")).toBeTruthy();
  });

  it("says so when value and PnL disagree", async () => {
    vi.mocked(api.portfolio).mockResolvedValue({ ...NOW, mismatch: [{ kind: "spot", drift: "4.20" }] });
    render(<PortfolioPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Spot");
  });
});

describe("portfolio kinds", () => {
  it("keeps the stack order and never drops a kind the history held", () => {
    expect(heldKinds(NOW)).toEqual(["perps", "spot", "staking"]);
    expect(historyKinds(HISTORY.points, heldKinds(NOW))).toEqual(["perps", "spot", "llp", "staking"]);
  });
});
