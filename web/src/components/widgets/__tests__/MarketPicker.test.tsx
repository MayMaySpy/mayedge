// @vitest-environment jsdom
import "@/test/dom";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MarketPicker } from "@/components/widgets/MarketPicker";
import type { Market } from "@/lib/api";
import { applyMarketQuotes, clearMarketQuotes } from "@/lib/liveData";

const STRK: Market = {
  market_index: 104,
  symbol: "STRK",
  price_decimals: 5,
  size_decimals: 1,
  is_perp: true,
  change_24h: -1.38,
};

describe("MarketPicker", () => {
  afterEach(() => {
    cleanup();
    clearMarketQuotes();
  });

  it("moves the 24h change beside the symbol with the live quote", async () => {
    render(<MarketPicker markets={[STRK]} symbol="STRK" onSymbolChange={() => {}} />);
    expect(screen.getByText(/1[.,]38%/)).toBeTruthy();

    act(() => applyMarketQuotes([{ market_index: 104, change_24h: 17.45 }]));

    expect(await screen.findByText(/17[.,]45%/)).toBeTruthy();
  });
});
