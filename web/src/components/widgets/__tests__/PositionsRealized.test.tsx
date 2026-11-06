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
  funding_paid: "-9",
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
  funding: "1.25",
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

function columnCell(name: RegExp): HTMLElement {
  const head = screen.getByRole("columnheader", { name });
  const col = Array.from(head.parentElement!.children).indexOf(head);
  const row = screen.getAllByRole("row")[1]!;
  return row.children[col] as HTMLElement;
}

function realizedCell(): HTMLElement {
  return columnCell(/^Realized$/);
}

function fundingCell(): HTMLElement {
  return columnCell(/^Funding$/);
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
  it("shows Realized PnL as the open Round trip's final value, and the tooltip is the breakdown", () => {
    setJournalOpen([TRIP]);
    setup();
    const cell = realizedCell();
    expect(cell.textContent).toBe("+7.50");
    expect(cell.className).toContain("text-bid");
    expect(cell.title).toBe("Closes +10.00, fees -2.00, funding +1.25");
    const funding = fundingCell();
    expect(funding.textContent).toBe("+1.25");
    expect(funding.title).toBe("Funding since this Position opened");
  });

  it("shows Realized PnL when nothing has closed and only funding has printed", () => {
    setJournalOpen([{ ...TRIP, realized: "0", pnl: "0", fees: "0", funding: "-0.5", net: "-0.5" }]);
    setup();
    const cell = realizedCell();
    expect(cell.textContent).toBe("-0.50");
    expect(cell.className).toContain("text-ask");
    expect(cell.title).toBe("Closes 0.00, fees 0.00, funding -0.50");
    expect(fundingCell().textContent).toBe("-0.50");
  });

  it("shows a dash until the journal has the Position", () => {
    setJournalOpen([{ ...TRIP, side: "short" }]);
    setup();
    expect(realizedCell().textContent).toBe("—");
    expect(fundingCell().textContent).toBe("—");
  });

  it("marks a Round trip older than the journal", () => {
    setJournalOpen([{ ...TRIP, partial: true }]);
    setup();
    expect(realizedCell().textContent).toBe("~+7.50");
    const funding = fundingCell();
    expect(funding.textContent).toBe("~+1.25");
    expect(funding.title).toBe(
      "Funding since this Position opened. Prints before the journal began are not in it."
    );
  });
});
