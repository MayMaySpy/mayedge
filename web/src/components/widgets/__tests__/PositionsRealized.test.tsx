// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PositionsPanel } from "@/components/widgets/PositionsPanel";
import type { Market, Position } from "@/lib/api";
import { setAccount, setFeedHealth, setJournalOpen, type OpenTripRealized } from "@/lib/liveData";

const ETH: Market = {
  market_index: 1,
  symbol: "ETH",
  price_decimals: 2,
  size_decimals: 2,
  min_base_amount: 0.01,
  min_quote_amount: 1,
  mark_price: 110,
  last_trade_price: 110,
  max_leverage: 10,
  allowed_leverages: [1, 2, 5, 10],
  is_perp: true,
};

const LONG: Position = {
  market_index: 1,
  symbol: "ETH",
  size: "1",
  entry_price: "100",
  mark_price: "110",
  unrealized_pnl: "10",
  leverage: 5,
  margin_mode: "cross",
  funding_paid: "-0.5",
  side: "long",
};

const TRIP: OpenTripRealized = {
  market_index: 1,
  symbol: "ETH",
  side: "long",
  trip_key: "1:a",
  open_ts: 1_700_000_000,
  realized: "8",
  pnl: "10",
  fees: "2",
  funding: "-0.5",
  net: "7.5",
  partial: false,
};

function setup() {
  render(
    <TooltipProvider>
      <PositionsPanel market={ETH} markets={[ETH]} tradingEnabled connected />
    </TooltipProvider>
  );
}

function realizedCell(): HTMLElement {
  const head = screen.getByRole("columnheader", { name: "Realized" });
  const col = Array.from(head.parentElement!.children).indexOf(head);
  const row = screen.getAllByRole("row")[1]!;
  return row.children[col] as HTMLElement;
}

beforeEach(() => {
  localStorage.clear();
  setFeedHealth({ market_ws: "live", account_ws: "live" });
  setAccount({
    collateral: "1000",
    available: "1000",
    unrealized_pnl: "10",
    positions: [LONG],
    open_orders: [],
  });
});

afterEach(() => {
  cleanup();
  setAccount(null);
  setJournalOpen([]);
});

describe("Positions Realized", () => {
  it("shows what the open Round trip has closed, less fees", () => {
    setJournalOpen([TRIP]);
    setup();
    const cell = realizedCell();
    expect(cell.textContent).toBe("+8.00");
    expect(cell.className).toContain("text-bid");
    expect(cell.title).toContain("Net +7.50, as the Journal counts it");
  });

  it("shows a dash until the journal has the Position", () => {
    setJournalOpen([{ ...TRIP, side: "short" }]);
    setup();
    expect(realizedCell().textContent).toBe("—");
  });

  it("marks a Round trip older than the journal", () => {
    setJournalOpen([{ ...TRIP, partial: true }]);
    setup();
    expect(realizedCell().textContent).toBe("~+8.00");
  });
});
