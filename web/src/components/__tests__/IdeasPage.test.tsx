// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IdeasPage as Page } from "@/components/IdeasPage";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, type Market } from "@/lib/api";
import type { Idea } from "@/lib/api.gen";

vi.mock("@/lib/notify", () => ({
  notifyErr: vi.fn(),
  notifyOk: vi.fn(),
  notifyWarn: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: vi.fn() }));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dashed: 2, Dotted: 1 },
  CandlestickSeries: "Candle",
  HistogramSeries: "Histogram",
  LineSeries: "Line",
  createChart: () => ({
    addSeries: () => ({
      setData() {},
      update() {},
      createPriceLine() {},
    }),
    timeScale: () => ({ fitContent() {} }),
    remove() {},
  }),
}));

const sockets = vi.fn();

function idea(over: Partial<Idea> = {}): Idea {
  return {
    id: "idea-1",
    symbol: "ZRO",
    side: "long",
    status: "watching",
    conviction: 2,
    horizon: "swing",
    thesis: "Unlock overhang gone after the 20th.",
    invalidation: "",
    trigger: "",
    tags: [],
    catalysts: [],
    entry_low: "2.18",
    entry_high: "2.20",
    stop: "2.08",
    targets: [{ price: "2.40", pct: null }],
    planner_ids: [],
    outcome: null,
    review: "",
    created_at: 1,
    updated_at: 2,
    closed_at: null,
    plan_entry: "2.19",
    r: "0.11",
    r_multiples: ["1.91"],
    ...over,
  };
}

function market(symbol: string, last: number): Market {
  return {
    market_index: symbol === "ZRO" ? 1 : 2,
    symbol,
    price_decimals: 2,
    size_decimals: 1,
    last_trade_price: last,
    is_perp: true,
  };
}

const ZRO = idea();
const HYPE = idea({
  id: "idea-2",
  symbol: "HYPE",
  entry_low: "3",
  entry_high: "4",
  stop: "2",
  plan_entry: "3.5",
  r: "1.5",
  targets: [{ price: "5", pct: null }],
  r_multiples: ["1.00"],
  thesis: "A slower bid under the listing.",
});

let rows: Idea[] = [];

function IdeasPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

beforeEach(() => {
  rows = [];
  sockets.mockClear();
  window.history.replaceState(null, "", "/ideas");
  vi.stubGlobal(
    "WebSocket",
    class {
      constructor() {
        sockets();
      }
    },
  );
  vi.spyOn(api, "ideas").mockImplementation(async () => ({ ideas: rows }));
  vi.spyOn(api, "idea").mockImplementation(async (id: string) => ({
    idea: rows.find((row) => row.id === id) ?? ZRO,
    log: [],
  }));
  vi.spyOn(api, "markets").mockResolvedValue([market("ZRO", 2.19), market("HYPE", 1)]);
  vi.spyOn(api, "candles").mockResolvedValue([]);
  vi.spyOn(api, "journalTrips").mockResolvedValue({ trips: [] });
  vi.spyOn(api, "ideaAlerts").mockResolvedValue({ alerts: [] });
  vi.spyOn(api, "pushStatus").mockResolvedValue({ enabled: true, chat_set: true, alerts: "held", algos: "lifecycle" });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("IdeasPage", () => {
  it("shows an empty desk", async () => {
    render(<IdeasPage />);
    expect(await screen.findByText("No Ideas yet")).toBeTruthy();
    expect(screen.getByText("An Idea is a Market, why you want it, and where you'd be wrong.")).toBeTruthy();
    expect(sockets).not.toHaveBeenCalled();
  });

  it("sorts nearest entry with in-zone first", async () => {
    rows = [HYPE, ZRO];
    render(<IdeasPage />);
    await screen.findByText("In zone");
    const body = screen.getAllByRole("row").map((row) => row.textContent ?? "");
    const zro = body.findIndex((text) => text.includes("ZRO"));
    const hype = body.findIndex((text) => text.includes("HYPE"));
    expect(zro).toBeGreaterThan(-1);
    expect(hype).toBeGreaterThan(zro);
  });

  it("marks in zone and past stop", async () => {
    rows = [ZRO, HYPE];
    render(<IdeasPage />);
    const zro = await screen.findByRole("row", { name: /ZRO/ });
    const hype = screen.getByRole("row", { name: /HYPE/ });
    expect(zro.className).toContain("bid");
    expect(screen.getByText("In zone")).toBeTruthy();
    expect(hype.className).toContain("warn");
    expect(screen.getByText("Past stop")).toBeTruthy();
    expect(sockets).not.toHaveBeenCalled();
  });

  it("refuses an empty Why", async () => {
    const user = userEvent.setup();
    render(<IdeasPage />);
    await screen.findByText("No Ideas yet");
    await user.click(screen.getAllByRole("button", { name: "New idea" })[0]);
    expect(screen.getByText(/A Thesis needs at least 10 characters/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Create" }) as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText("Why"), "no");
    expect((screen.getByRole("button", { name: "Create" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows R and refuses a long stop above the zone", async () => {
    rows = [ZRO];
    const user = userEvent.setup();
    render(<IdeasPage />);
    await user.click(await screen.findByRole("row", { name: /ZRO/ }));
    await user.click(screen.getByRole("tab", { name: "Plan" }));
    expect(screen.getByText(/R 0\.11/)).toBeTruthy();
    const stop = screen.getByLabelText("Stop");
    await user.clear(stop);
    await user.type(stop, "3");
    expect(screen.getByText("A long stop sits below the entry.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("pings the desk and opens a tab when nobody answers", async () => {
    rows = [ZRO];
    const posted: unknown[] = [];
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        postMessage(data: unknown) {
          posted.push(data);
        }
        addEventListener() {}
        removeEventListener() {}
        close() {}
      },
    );
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<IdeasPage />);
    await userEvent.click(await screen.findByRole("row", { name: /ZRO/ }));
    vi.useFakeTimers();
    screen.getByRole("button", { name: "Draft on chart" }).click();
    await vi.advanceTimersByTimeAsync(500);
    expect(posted.some((msg) => (msg as { type?: string }).type === "desk-ping")).toBe(true);
    expect(open.mock.calls[0]?.[0]).toBe("/ZRO?idea=idea-1");
    expect(open.mock.calls[0]?.[1]).toBe("_blank");
    expect(sockets).not.toHaveBeenCalled();
  });
});
