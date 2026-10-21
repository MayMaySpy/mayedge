// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PortfolioPage as Page } from "@/components/PortfolioPage";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, type PortfolioHistory, type PortfolioNow } from "@/lib/api";
import { flowEvents, heldKinds, historyKinds } from "@/lib/portfolioDay";

vi.mock("@/lib/notify", () => ({ notifyErr: vi.fn(), notifyOk: vi.fn() }));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  HistogramSeries: "Histogram",
  LineSeries: "Line",
  createChart: () => ({
    addSeries: () => ({ setData() {} }),
    timeScale: () => ({
      fitContent() {},
      timeToCoordinate: () => 120,
      subscribeSizeChange() {},
      unsubscribeSizeChange() {},
    }),
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

/** The app wraps every page in one TooltipProvider; the Flow chips need it. */
function PortfolioPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

beforeEach(() => {
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

  it("charts a kind held earlier in the range, and puts each Flow in a lane under the plot", async () => {
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    // LLP holds nothing now but did in the range: it keeps a column and a line.
    const days = screen.getByText("2026-10-19").closest("table") as HTMLElement;
    expect(within(days).getByText("LLP")).toBeTruthy();
    // LLP −539.41 and Perps +539.41 at one moment: one move, not two arrows.
    expect(await screen.findByRole("button", { name: "Moved $539.41 LLP → Perps" })).toBeTruthy();
    expect(within(days).getByText("Day (UTC)")).toBeTruthy();
  });

  it("lists what each Holding is made of", async () => {
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    expect(screen.getByText("ETH")).toBeTruthy();
    expect(screen.getByText("1,018.21 LIT")).toBeTruthy();
    expect(screen.getByText("27.59%")).toBeTruthy();
    expect(screen.getByText("Not in LLP")).toBeTruthy();
    // One card per kind, in the Allocation's order, each headed by its value, share and change.
    const cards = ["Perps", "Spot", "LLP", "Staking"].map((name) => screen.getByRole("heading", { name }));
    for (const [a, b] of cards.slice(1).map((card, i) => [cards[i], card])) {
      expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    const staking = cards[3].closest("header") as HTMLElement;
    expect(within(staking).getByText("57%")).toBeTruthy();
    expect(within(staking).getByText("+143.04")).toBeTruthy();
  });

  it("says so when value and PnL disagree", async () => {
    vi.mocked(api.portfolio).mockResolvedValue({ ...NOW, mismatch: [{ kind: "spot", drift: "4.20" }] });
    render(<PortfolioPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Spot");
  });
});

describe("PortfolioPage days, calendar and card", () => {
  // 25 UTC days ending today, so the calendar's default month holds the last one.
  const today = Date.now() - (Date.now() % 86_400_000);
  const label = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const newest = label(today);
  const oldest = label(today - 24 * 86_400_000);
  const many = Array.from({ length: 25 }, (_, i) => {
    const start = today - (24 - i) * 86_400_000;
    return {
      day: new Date(start).toISOString().slice(0, 10),
      start,
      kinds: { perps: String(i + 1), spot: "0", llp: "0", staking: "0" },
      total: String(i + 1),
    };
  });

  it("pages the days, newest first, and exports them all as CSV", async () => {
    vi.mocked(api.portfolioDays).mockResolvedValue({ range: "30d", days: many });
    const saved: Blob[] = [];
    URL.createObjectURL = vi.fn((b: Blob) => {
      saved.push(b);
      return "blob:x";
    });
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    const table = (await screen.findByText("Day (UTC)")).closest("table") as HTMLElement;
    expect(within(table).getByText(newest)).toBeTruthy();
    expect(within(table).queryByText(oldest)).toBeNull();
    expect(screen.getByText("1–20 of 25")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Older" }));
    expect(within(table).getByText(oldest)).toBeTruthy();
    expect(screen.getByText("21–25 of 25")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(click).toHaveBeenCalledOnce();
    const csv = await saved[0].text();
    expect(csv.split("\n")[0]).toBe("day_utc,perps,spot,llp,staking,total");
    expect(csv.trim().split("\n")).toHaveLength(26);
  });

  it("fills a page with as many days as the table's height holds", async () => {
    vi.mocked(api.portfolioDays).mockResolvedValue({ range: "30d", days: many });
    // Header and rows 30px each in a 330px box: room for ten rows under the header.
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ height: 30 } as DOMRect);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(330);
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    expect(await screen.findByText("1–10 of 25")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Older" }));
    expect(screen.getByText("11–20 of 25")).toBeTruthy();
  });

  it("opens the calendar in a modal, loading every day only then", async () => {
    vi.mocked(api.portfolioDays).mockResolvedValue({ range: "all", days: many });
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    expect(screen.queryByRole("grid")).toBeNull();
    expect(vi.mocked(api.portfolioDays).mock.calls.map((c) => c[0])).not.toContain("all");
    await userEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(vi.mocked(api.portfolioDays).mock.calls.map((c) => c[0])).toContain("all");
    const grid = await screen.findByRole("grid", { name: /PnL calendar/ });
    const cell = within(grid).getByTitle(new RegExp(`^${newest}: \\+25`));
    expect(cell.getAttribute("style")).toContain("color-mix");
  });

  it("opens the PnL card with its range picker and $ switch", async () => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never;
    render(<PortfolioPage />);
    await screen.findByText("$5,681.19");
    await userEvent.click(screen.getByRole("button", { name: "PnL card" }));
    expect(await screen.findByRole("img", { name: "PnL card preview" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Show $" }).getAttribute("aria-checked")).toBe("true");
    await userEvent.click(screen.getByRole("radio", { name: "30d" }));
    expect(vi.mocked(api.portfolioHistory).mock.calls.map((c) => c[0])).toContain("30d");
  });
});

describe("portfolio kinds", () => {
  it("keeps the stack order and never drops a kind the history held", () => {
    expect(heldKinds(NOW)).toEqual(["perps", "spot", "staking"]);
    expect(historyKinds(HISTORY.points, heldKinds(NOW))).toEqual(["perps", "spot", "llp", "staking"]);
  });
});

describe("flow events", () => {
  it("reads a moment whose Flows cancel as a move, and a net as money in or out", () => {
    const events = flowEvents([
      { ts: 1, kind: "llp", amount: "-539.41" },
      { ts: 1, kind: "perps", amount: "539.41" },
      { ts: 2, kind: "perps", amount: "500" },
      { ts: 3, kind: "spot", amount: "-120.5" },
      { ts: 4, kind: "perps", amount: "0" },
    ]);
    expect(events.map((e) => [e.ts, e.kind, e.label])).toEqual([
      [1, "move", "Moved $539.41 LLP → Perps"],
      [2, "in", "Deposit $500.00 into Perps"],
      [3, "out", "Withdrawal $120.50 from Spot"],
    ]);
  });
});
