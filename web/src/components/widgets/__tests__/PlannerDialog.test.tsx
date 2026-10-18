// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PlannerDialog } from "@/components/widgets/planner/PlannerDialog";
import { api, type Market, type PlannerPreview } from "@/lib/api";

vi.mock("@/lib/notify", () => ({
  notifyErr: vi.fn(),
  notifyOk: vi.fn(),
  notifyWarn: vi.fn(),
  notifyOrder: vi.fn(),
  notifyDesk: vi.fn(),
}));

const ETH: Market = {
  market_index: 1,
  symbol: "ETH",
  price_decimals: 2,
  size_decimals: 2,
  mark_price: 100,
  last_trade_price: 100,
  is_perp: true,
};

const DRAWN: PlannerPreview = {
  plan: {
    side: "buy",
    entry: "100",
    stop: "95",
    r: "5",
    size: "20",
    targets: [
      { index: 1, price: "110", qty: "10", pct: "50", r: "2", move_pct: "10" },
      { index: 2, price: "115", qty: "10", pct: "50", r: "3", move_pct: "15" },
    ],
    runner: "0",
    risk_usd: "100",
    risk_pct: "1",
    breakeven: "100.1",
    stop_pct: "-5",
    warnings: [],
    steps: [{ after: 1, price: "100.1", to: "breakeven" }],
  },
  refused: null,
  replaces: [],
  equity: "10000",
  mark: "100",
};

function setup(onOpenChange = vi.fn()) {
  render(<PlannerDialog open onOpenChange={onOpenChange} market={ETH} mode="enter" />);
  return { user: userEvent.setup(), onOpenChange };
}

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, "plannerPreview").mockResolvedValue(DRAWN);
  vi.spyOn(api, "algoStart").mockResolvedValue({ working: [], history: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const start = () => screen.getByRole("button", { name: "Plan long" }) as HTMLButtonElement;

describe("PlannerDialog", () => {
  it("draws the plan from the desk before it can start", async () => {
    const { user } = setup();
    expect(start().disabled).toBe(true);
    expect(screen.getByText("Set a stop")).toBeTruthy();
    await user.type(screen.getByLabelText("Entry price"), "100");
    await user.type(screen.getByLabelText("Stop"), "95");
    await waitFor(() => expect(screen.getByText(/= 1% of equity/)).toBeTruthy());
    expect(screen.getByText(/110/)).toBeTruthy();
    expect(start().disabled).toBe(false);
    const body = vi.mocked(api.plannerPreview).mock.calls.at(-1)?.[0];
    expect(body).toMatchObject({ mode: "enter", side: "buy", entry_price: "100", stop: "95", risk_pct: "1" });
  });

  it("starts the plan it showed", async () => {
    const { user, onOpenChange } = setup();
    await user.type(screen.getByLabelText("Entry price"), "100");
    await user.type(screen.getByLabelText("Stop"), "95");
    await waitFor(() => expect(start().disabled).toBe(false));
    await user.click(start());
    expect(api.algoStart).toHaveBeenCalledWith(
      "planner",
      expect.objectContaining({ stop: "95", entry_price: "100" })
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("sends the stop steps picked and draws each step", async () => {
    vi.mocked(api.plannerPreview).mockResolvedValue({
      ...DRAWN,
      plan: {
        ...DRAWN.plan!,
        steps: [
          { after: 1, price: "100.1", to: "breakeven" },
          { after: 2, price: "110", to: "tp1" },
        ],
      },
    });
    const { user } = setup();
    await user.type(screen.getByLabelText("Entry price"), "100");
    await user.type(screen.getByLabelText("Stop"), "95");
    await user.click(screen.getByRole("radio", { name: "Step up" }));
    await waitFor(() => expect(screen.getByText("At TP2, stop to")).toBeTruthy());
    expect(screen.getByText(/110,00 \(TP1, −4.35% from TP2\)|110\.00 \(TP1, −4.35% from TP2\)/)).toBeTruthy();
    const body = vi.mocked(api.plannerPreview).mock.calls.at(-1)?.[0];
    expect(body).toMatchObject({ stop_steps: "ladder" });
  });

  it("sends each target's order type, Limit unless picked", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Entry price"), "100");
    await user.type(screen.getByLabelText("Stop"), "95");
    const tp2 = screen.getByLabelText("Target 2 order type");
    await user.click(within(tp2).getByRole("radio", { name: "Trigger" }));
    await waitFor(() => {
      const body = vi.mocked(api.plannerPreview).mock.calls.at(-1)?.[0] as {
        targets: { order: string }[];
      };
      expect(body.targets.map((t) => t.order)).toEqual(["limit", "trigger"]);
    });
  });

  it("shows the rule a plan breaks and will not start it", async () => {
    vi.mocked(api.plannerPreview).mockResolvedValue({
      ...DRAWN,
      plan: null,
      refused: { rule: "S1", message: "The stop must be on the losing side of entry" },
    });
    const { user } = setup();
    await user.type(screen.getByLabelText("Entry price"), "100");
    await user.type(screen.getByLabelText("Stop"), "105");
    await waitFor(() => expect(screen.getByText(/S1 · The stop must be/)).toBeTruthy());
    expect(start().disabled).toBe(true);
  });

  it("sends a Chase entry's band, offset and clip, drawn from its worst fill", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Chase" }));
    expect(screen.queryByLabelText("Entry price")).toBeNull();
    await user.type(screen.getByLabelText("Chase band low"), "99");
    await user.type(screen.getByLabelText("Chase band high"), "100.5");
    await user.type(screen.getByLabelText("Chase clip ETH"), "1");
    await user.type(screen.getByLabelText("Stop"), "95");
    await waitFor(() => expect(screen.getByText("Entry, worst fill")).toBeTruthy());
    const body = vi.mocked(api.plannerPreview).mock.calls.at(-1)?.[0];
    expect(body).toMatchObject({
      entry_type: "chase",
      entry_price: null,
      entry_chase: { low: "99", high: "100.5", offset_bps: "4", clip: "1" },
    });
  });
});
