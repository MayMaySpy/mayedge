// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Header } from "@/components/widgets/Header";
import type { Market } from "@/lib/api";
import { setFeedHealth, setSendBudget } from "@/lib/liveData";

const ETH: Market = {
  market_index: 1,
  symbol: "ETH",
  price_decimals: 2,
  size_decimals: 2,
  mark_price: 100,
  last_trade_price: 100,
  is_perp: true,
};

function renderHeader() {
  render(
    <TooltipProvider>
      <Header
        markets={[ETH]}
        symbol="ETH"
        onSymbolChange={() => {}}
        network="mainnet"
        connected
        tradingEnabled
        editing={false}
        onEditToggle={() => {}}
        onResetLayout={() => {}}
      />
    </TooltipProvider>
  );
}

afterEach(() => {
  cleanup();
  setSendBudget({
    requests: 0,
    requests_cap: 54,
    tx: 0,
    tx_cap: 38,
    algo_tx_cap: 30,
    cooling_until: 0,
    refused_60s: 0,
  });
});

describe("send budget", () => {
  it("shows the last minute on the feed status", async () => {
    setFeedHealth({ market_ws: "live", account_ws: "live" });
    setSendBudget({ tx: 12, tx_cap: 38, requests: 20, requests_cap: 54, algo_tx_cap: 30 });
    renderHeader();
    await userEvent.hover(screen.getByRole("button", { name: "Live" }));
    const line = await screen.findByText("Sends 12/38 · Requests 20/54 · last 60s");
    expect(line.className).not.toContain("text-warn");
    expect(line.className).not.toContain("text-ask");
  });

  it("turns amber when sends reach the algo cap", async () => {
    setFeedHealth({ market_ws: "live", account_ws: "live" });
    setSendBudget({ tx: 30, tx_cap: 38, requests: 30, requests_cap: 54, algo_tx_cap: 30 });
    renderHeader();
    await userEvent.hover(screen.getByRole("button", { name: "Live" }));
    const line = await screen.findByText("Sends 30/38 · Requests 30/54 · last 60s");
    expect(line.className).toContain("text-warn");
  });

  it("turns red while cooling and names the UTC clock", async () => {
    setFeedHealth({ market_ws: "live", account_ws: "live" });
    setSendBudget({
      tx: 12,
      tx_cap: 38,
      requests: 20,
      requests_cap: 54,
      algo_tx_cap: 30,
      cooling_until: Date.UTC(2026, 9, 21, 14, 2, 10),
    });
    renderHeader();
    await userEvent.hover(screen.getByRole("button", { name: "Live" }));
    const line = await screen.findByText("Sends 12/38 · Requests 20/54 · last 60s");
    expect(line.className).toContain("text-ask");
    expect(screen.getByText("Lighter cooldown until 14:02:10 UTC")).toBeTruthy();
  });
});
