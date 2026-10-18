// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrderTicket } from "@/components/widgets/orderTicket/OrderTicket";
import { api, type Market, type Position } from "@/lib/api";
import {
  applyBookSnapshot,
  clearBook,
  setAccount,
  setBookSynced,
  setFeedHealth,
} from "@/lib/liveData";
import { notifyErr } from "@/lib/notify";

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
  min_base_amount: 0.01,
  min_quote_amount: 1,
  mark_price: 100,
  last_trade_price: 100,
  max_leverage: 10,
  allowed_leverages: [1, 2, 5, 10],
  is_perp: true,
};

function position(size: string): Position {
  return {
    market_index: 1,
    symbol: "ETH",
    size,
    entry_price: "100",
    mark_price: "100",
    unrealized_pnl: "0",
    leverage: 5,
    margin_mode: "cross",
  };
}

/** Bid 100 / ask 100.1, feeds live, $1,000 free: 50 ETH of room at 5x. */
function liveDesk(positions: Position[] = []) {
  setFeedHealth({ market_ws: "live", account_ws: "live" });
  applyBookSnapshot({
    bids: [{ price: "100", size: "50" }],
    asks: [{ price: "100.1", size: "50" }],
  });
  setAccount({
    collateral: "1000",
    available: "1000",
    trade_available: "1000",
    unrealized_pnl: "0",
    positions,
    open_orders: [],
  });
}

function setup(props: Partial<Parameters<typeof OrderTicket>[0]> = {}) {
  const onOrderPlaced = vi.fn();
  render(
    <OrderTicket market={ETH} tradingEnabled connected onOrderPlaced={onOrderPlaced} {...props} />
  );
  return { onOrderPlaced, user: userEvent.setup() };
}

const button = (name: string | RegExp) =>
  screen.getByRole("button", { name }) as HTMLButtonElement;

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, "placeMarketOrder").mockResolvedValue({ tx_hash: "0x1" } as never);
  vi.spyOn(api, "placeLimitOrder").mockResolvedValue({ tx_hash: "0x2" } as never);
  liveDesk();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.mocked(notifyErr).mockClear();
  setAccount(null);
  clearBook();
  setBookSynced(false);
  setFeedHealth({ market_ws: "down", account_ws: "down" });
});

describe("OrderTicket", () => {
  it("sends a market buy at the typed size", async () => {
    const { onOrderPlaced, user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.type(screen.getByLabelText("Size"), "1.5");
    await user.click(button("Buy"));

    expect(api.placeMarketOrder).toHaveBeenCalledTimes(1);
    expect(api.placeMarketOrder).toHaveBeenCalledWith({
      market_index: 1,
      side: "buy",
      size: "1.5",
      slippage: 0.01,
      reduce_only: false,
    });
    expect(api.placeLimitOrder).not.toHaveBeenCalled();
    expect(onOrderPlaced).toHaveBeenCalledTimes(1);
  });

  it("sends a resting limit sell at the typed price", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Limit" }));
    await user.type(screen.getByLabelText("Size"), "2");
    await user.type(screen.getByLabelText("Price"), "105.5");
    await user.click(button("Sell"));

    expect(api.placeLimitOrder).toHaveBeenCalledWith({
      market_index: 1,
      side: "sell",
      size: "2",
      price: "105.5",
      time_in_force: "gtt",
      reduce_only: false,
    });
  });

  it("sends the time in force that was picked", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Limit" }));
    await user.type(screen.getByLabelText("Size"), "2");
    await user.type(screen.getByLabelText("Price"), "99");
    await user.click(screen.getByRole("radio", { name: "Post" }));
    await user.click(button("Buy"));

    expect(api.placeLimitOrder).toHaveBeenCalledWith(
      expect.objectContaining({ side: "buy", time_in_force: "post_only" })
    );
  });

  it("will not send without a size", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    expect(screen.getByText("Enter size")).toBeTruthy();
    for (const b of screen.getAllByRole("button", { name: /Buy|Sell/ })) {
      expect((b as HTMLButtonElement).disabled).toBe(true);
      await user.click(b);
    }
    expect(api.placeMarketOrder).not.toHaveBeenCalled();
  });

  it("will not send past the size the margin allows", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.type(screen.getByLabelText("Size"), "500");

    const blocked = screen.getAllByRole("button", { name: /^Max / }) as HTMLButtonElement[];
    expect(blocked).toHaveLength(2);
    for (const b of blocked) {
      expect(b.disabled).toBe(true);
      await user.click(b);
    }
    expect(api.placeMarketOrder).not.toHaveBeenCalled();
  });

  it("will not send while the account feed is down", async () => {
    setFeedHealth({ market_ws: "live", account_ws: "down" });
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.type(screen.getByLabelText("Size"), "1");

    expect(screen.getByText("Account feed down")).toBeTruthy();
    for (const b of screen.getAllByRole("button", { name: /Buy|Sell/ })) {
      expect((b as HTMLButtonElement).disabled).toBe(true);
    }
    expect(api.placeMarketOrder).not.toHaveBeenCalled();
  });

  it("will not send while the desk is read-only", async () => {
    const { user } = setup({ tradingEnabled: false });
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.type(screen.getByLabelText("Size"), "1");

    expect(screen.getByText("Trading not configured")).toBeTruthy();
    for (const b of screen.getAllByRole("button", { name: /Buy|Sell/ })) {
      expect((b as HTMLButtonElement).disabled).toBe(true);
    }
    expect(api.placeMarketOrder).not.toHaveBeenCalled();
  });

  it("blocks a usd-sized sell priced far under the bid, and only the sell", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Limit" }));
    await user.type(screen.getByLabelText("Price"), "10");
    await user.click(button("ETH"));
    await user.type(screen.getByLabelText("Size"), "100");

    const sell = button("Price far below bid — size in ETH");
    expect(sell.disabled).toBe(true);
    await user.click(sell);
    expect(api.placeLimitOrder).not.toHaveBeenCalled();

    // The buy rests at $10: 10 ETH for the $100 typed.
    await user.click(button("Buy"));
    expect(api.placeLimitOrder).toHaveBeenCalledWith(
      expect.objectContaining({ side: "buy", size: "10", price: "10" })
    );
  });

  it("sizes a usd order from the price it works at", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Limit" }));
    await user.type(screen.getByLabelText("Price"), "99.5");
    await user.click(button("ETH"));
    await user.type(screen.getByLabelText("Size"), "199");
    await user.click(button("Sell"));

    expect(api.placeLimitOrder).toHaveBeenCalledWith(
      expect.objectContaining({ side: "sell", size: "2", price: "99.5" })
    );
  });

  it("closes no more than the Position when Close is on", async () => {
    liveDesk([position("3")]);
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.click(button("Close"));
    await user.type(screen.getByLabelText("Size"), "3");
    await user.click(button("Sell"));

    expect(api.placeMarketOrder).toHaveBeenCalledWith(
      expect.objectContaining({ side: "sell", size: "3", reduce_only: true })
    );

    // A larger size is cut to the Position, never sent as typed.
    await user.clear(screen.getByLabelText("Size"));
    await user.type(screen.getByLabelText("Size"), "9");
    await user.click(button("Sell"));
    expect(api.placeMarketOrder).toHaveBeenLastCalledWith(
      expect.objectContaining({ side: "sell", size: "3", reduce_only: true })
    );
  });

  it("reports a refused order and does not count it as placed", async () => {
    vi.mocked(api.placeMarketOrder).mockRejectedValueOnce(
      new Error("Order notional $100,100 exceeds limit $50,000")
    );
    const { onOrderPlaced, user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.type(screen.getByLabelText("Size"), "1");
    await user.click(button("Buy"));

    expect(notifyErr).toHaveBeenCalledWith("Order notional $100,100 exceeds limit $50,000");
    expect(onOrderPlaced).not.toHaveBeenCalled();
    expect(button("Buy").disabled).toBe(false);
  });

  it("sends once when the button is clicked twice in a row", async () => {
    let release: (v: unknown) => void = () => {};
    vi.mocked(api.placeMarketOrder).mockImplementationOnce(
      () => new Promise((resolve) => (release = resolve)) as never
    );
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: "Market" }));
    await user.type(screen.getByLabelText("Size"), "1");
    await user.click(button("Buy"));
    await user.click(button("Sending…"));
    expect(api.placeMarketOrder).toHaveBeenCalledTimes(1);
    release({ tx_hash: "0x1" });
  });

  it("plans the open Position's exit instead of a new entry", async () => {
    liveDesk([position("-2")]);
    const { user } = setup();
    await user.click(button("Chase"));
    await user.click(await screen.findByRole("menuitem", { name: "Plan Position…" }));

    expect(await screen.findByRole("heading", { name: "Plan ETH short" })).toBeTruthy();
    expect(screen.queryByRole("radiogroup", { name: "Entry type" })).toBeNull();
  });

  it("opens a new entry's Planner while the Market is flat", async () => {
    const { user } = setup();
    await user.click(button("Chase"));
    await user.click(await screen.findByRole("menuitem", { name: "Planner…" }));

    expect(await screen.findByRole("heading", { name: "Planner · ETH" })).toBeTruthy();
  });

  it("starts a Chase entry from the ticket's Chase", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Size"), "2");
    await user.type(screen.getByLabelText("Clip"), "1");
    await user.type(screen.getByLabelText("Floor"), "99");
    await user.type(screen.getByLabelText("Ceiling"), "100.5");
    await user.click(button("Chase"));
    await user.click(await screen.findByRole("menuitem", { name: "Planner…" }));

    const chase = await screen.findByRole("radio", { name: "Chase" });
    expect(chase.getAttribute("aria-checked") ?? chase.getAttribute("data-state")).toMatch(/true|on|checked/);
    expect((screen.getByLabelText("Chase band low") as HTMLInputElement).value).toBe("99");
    expect((screen.getByLabelText("Chase band high") as HTMLInputElement).value).toBe("100.5");
    expect((screen.getByLabelText("Chase clip ETH") as HTMLInputElement).value).toBe("1");
    expect((screen.getByLabelText("Size ETH") as HTMLInputElement).value).toBe("2");
  });
});

