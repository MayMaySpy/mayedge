// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Header } from "@/components/widgets/Header";
import { api, type Market, type Position } from "@/lib/api";
import { setAccount, setAlgo, setAutoKill, setFeedHealth } from "@/lib/liveData";
import { notifyErr, notifyOk, notifyWarn } from "@/lib/notify";

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

const LONG: Position = {
  market_index: 1,
  symbol: "ETH",
  size: "2",
  entry_price: "100",
  mark_price: "100",
  unrealized_pnl: "0",
  leverage: 5,
  margin_mode: "cross",
};

const DISARMED = {
  armed: false,
  loss_usd: null,
  profit_usd: null,
  fired_at: null,
  fired_reason: null,
  fired_upnl: null,
  last_kill_status: null,
};

function setup(props: Partial<Parameters<typeof Header>[0]> = {}) {
  render(
    <TooltipProvider>
      <Header
        markets={[ETH]}
        symbol="ETH"
        onSymbolChange={() => {}}
        network="testnet"
        connected
        tradingEnabled
        editing={false}
        onEditToggle={() => {}}
        onResetLayout={() => {}}
        {...props}
      />
    </TooltipProvider>
  );
  return userEvent.setup();
}

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

beforeEach(() => {
  localStorage.clear();
  setFeedHealth({ market_ws: "live", account_ws: "live" });
  setAutoKill(DISARMED);
  setAccount({
    collateral: "1000",
    available: "1000",
    unrealized_pnl: "0",
    positions: [LONG],
    open_orders: [],
  });
  vi.spyOn(api, "kill").mockResolvedValue({ status: "killed", cancel_ok: true, flatten: [] });
  vi.spyOn(api, "setAutoKill").mockImplementation(async (body) => ({
    ...DISARMED,
    armed: body.armed,
    loss_usd: body.loss_usd ?? null,
    profit_usd: body.profit_usd ?? null,
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  for (const fn of [notifyErr, notifyOk, notifyWarn]) vi.mocked(fn).mockClear();
  setAccount(null);
  setAutoKill(DISARMED);
  setAlgo({ working: [], history: [] });
});

describe("Kill switch", () => {
  it("warns that Stop + cancel leaves a Planner's Position with no stop", async () => {
    setAlgo({
      working: [
        { type: "algo", id: "planner", algo_type: "planner", algo_id: "PL-0001", status: "running", symbol: "ETH" },
      ],
      history: [],
    });
    const user = setup();
    await user.click(button("Kill"));
    expect(screen.getByText(/A Planner is live/)).toBeTruthy();
  });

  it("says nothing about Planner when none is live", async () => {
    const user = setup();
    await user.click(button("Kill"));
    expect(screen.queryByText(/Planner is live/)).toBeNull();
  });

  it("does nothing until a choice is made in the dialog", async () => {
    const user = setup();
    await user.click(button("Kill"));
    expect(screen.getByText("Kill switch")).toBeTruthy();
    expect(screen.getByText(/Flatten: 1 position/)).toBeTruthy();
    expect(api.kill).not.toHaveBeenCalled();

    await user.click(button("Cancel"));
    expect(api.kill).not.toHaveBeenCalled();
  });

  it("stops and cancels without flattening", async () => {
    const user = setup();
    await user.click(button("Kill"));
    await user.click(button("Stop + cancel"));

    expect(api.kill).toHaveBeenCalledTimes(1);
    expect(api.kill).toHaveBeenCalledWith(false);
    expect(notifyOk).toHaveBeenCalledWith("Kill: algos stopped, orders cancelled");
  });

  it("flattens only from the flatten button", async () => {
    const user = setup();
    await user.click(button("Kill"));
    await user.click(button("Stop + flatten"));

    expect(api.kill).toHaveBeenCalledTimes(1);
    expect(api.kill).toHaveBeenCalledWith(true);
    expect(notifyOk).toHaveBeenCalledWith("Kill: algos stopped, orders cancelled, flatten sent");
  });

  it("names the steps that failed on a partial Kill", async () => {
    vi.mocked(api.kill).mockResolvedValueOnce({
      status: "partial",
      cancel_ok: false,
      cancel_error: "venue down",
      algo_error: "grid would not stop",
      flatten: [{ market_index: 1, symbol: "ETH", ok: false, error: "venue down" }],
    });
    const user = setup();
    await user.click(button("Kill"));
    await user.click(button("Stop + flatten"));

    expect(notifyOk).not.toHaveBeenCalled();
    expect(notifyWarn).toHaveBeenCalledWith(
      "Kill partial",
      "Failed: algo stop, cancel-all, flatten. Check positions and open orders"
    );
  });

  it("reports a Kill the desk could not send", async () => {
    vi.mocked(api.kill).mockRejectedValueOnce(new Error("Failed to fetch"));
    const user = setup();
    await user.click(button("Kill"));
    await user.click(button("Stop + cancel"));

    expect(notifyErr).toHaveBeenCalledWith("Failed to fetch");
    // Still open, and usable again, so Kill can be retried at once.
    await waitFor(() => expect(button("Stop + cancel").disabled).toBe(false));
  });

  it("offers no Kill on a read-only desk", () => {
    setup({ tradingEnabled: false });
    expect(screen.queryByRole("button", { name: "Kill" })).toBeNull();
    expect(screen.getByText("Read-only")).toBeTruthy();
  });
});

describe("Auto kill", () => {
  it("arms with the loss floor that was typed", async () => {
    const user = setup();
    await user.click(button("Kill"));
    await user.type(screen.getByPlaceholderText("500"), "250");
    await user.click(button("Arm auto kill"));

    expect(api.setAutoKill).toHaveBeenCalledWith({ armed: true, loss_usd: 250, profit_usd: null });
    expect(notifyOk).toHaveBeenCalledWith("Auto kill armed");
    // Armed: the limits lock and the header shows them.
    await waitFor(() => expect(button("Disarm")).toBeTruthy());
    expect((screen.getByPlaceholderText("500") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/Auto kill -250/)).toBeTruthy();
  });

  it("will not arm without a limit", async () => {
    const user = setup();
    await user.click(button("Kill"));
    await user.click(button("Arm auto kill"));

    expect(api.setAutoKill).not.toHaveBeenCalled();
    expect(notifyErr).toHaveBeenCalledWith("Set a loss floor or profit target");
  });

  it("will not arm with a limit that is not a positive number", async () => {
    const user = setup();
    await user.click(button("Kill"));
    await user.type(screen.getByPlaceholderText("500"), "-50");
    await user.click(button("Arm auto kill"));

    expect(api.setAutoKill).not.toHaveBeenCalled();
  });

  it("disarms without touching Positions", async () => {
    setAutoKill({ ...DISARMED, armed: true, loss_usd: 250 });
    const user = setup();
    await user.click(button("Kill"));
    await user.click(button("Disarm"));

    expect(api.setAutoKill).toHaveBeenCalledWith({ armed: false, loss_usd: 250, profit_usd: null });
    expect(api.kill).not.toHaveBeenCalled();
  });

  it("shows what it did the last time it fired", async () => {
    setAutoKill({
      ...DISARMED,
      fired_at: 1_760_000_000_000,
      fired_reason: "loss",
      fired_upnl: -312.5,
      last_kill_status: "partial",
    });
    const user = setup();
    await user.click(button("Kill"));
    expect(screen.getByText(/Last fired: loss · .*312\.50 · partial/)).toBeTruthy();
  });
});

describe("Header pages", () => {
  it("links the Portfolio and the Journal, read-only or not", () => {
    setup({ tradingEnabled: false });
    expect(screen.getByRole("link", { name: "Portfolio" }).getAttribute("href")).toBe("/portfolio");
    expect(screen.getByRole("link", { name: "Journal" }).getAttribute("href")).toBe("/journal");
  });
});
