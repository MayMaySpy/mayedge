// @vitest-environment jsdom
import "@/test/dom";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MassagerParamsSheet } from "@/components/widgets/orderTicket/kinds/MassagerParamsSheet";
import { massagerPlugin } from "@/lib/algoPlugins/massagerPlugin";
import { api, type Market } from "@/lib/api";
import { setAccount, setAlgo } from "@/lib/liveData";
import type { MassagerParamsState } from "@/lib/massager";

const LIT: Market = {
  market_index: 120,
  symbol: "LIT",
  price_decimals: 4,
  size_decimals: 0,
  min_base_amount: 10,
  min_quote_amount: 1,
  mark_price: 3.35,
  last_trade_price: 3.35,
  max_leverage: 5,
  allowed_leverages: [1, 5],
  is_perp: true,
};

/** 48 closed 1h candles swinging 3.30–3.40: Ranging, a day's range of 3.28 to 3.42. */
function candles() {
  const now = Math.floor(Date.now() / 3_600_000) * 3600;
  return Array.from({ length: 48 }, (_, i) => {
    const close = i % 2 === 0 ? 3.3 : 3.4;
    return { time: now - (48 - i) * 3600, open: close, high: close + 0.02, low: close - 0.02, close, volume: 1 };
  });
}

let last: MassagerParamsState | null = null;

function Sheet({ swing }: { swing: number }) {
  const [state, setState] = useState<MassagerParamsState>(massagerPlugin.defaultState);
  last = state;
  return (
    <MassagerParamsSheet market={LIT} bookMid={3.35} sizeNum={swing} state={state} onStateChange={setState} />
  );
}

beforeEach(() => {
  vi.spyOn(api, "candles").mockResolvedValue(candles() as never);
  vi.spyOn(api, "massagerCarry").mockResolvedValue({
    carried: true,
    why: "Carried",
    source: "MS-0004",
    basis: "3.2697",
    entry: "3.2772",
    captured: "7.07",
    runs: 2,
  });
  setAccount({
    collateral: "1000",
    available: "1000",
    trade_available: "1000",
    unrealized_pnl: "0",
    positions: [
      {
        market_index: 120,
        symbol: "LIT",
        size: "1000",
        entry_price: "3.30",
        mark_price: "3.35",
        unrealized_pnl: "0",
        leverage: 5,
        margin_mode: "cross",
      },
    ],
    open_orders: [],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setAccount(null);
  setAlgo(null);
});

describe("Massager ticket (massager-rules MS19, MS24)", () => {
  it("reads the day as Ranging and fills the Band from its range in one press", async () => {
    const user = userEvent.setup();
    render(<Sheet swing={300} />);
    expect(await screen.findByText("Ranging")).toBeTruthy();
    await user.click(screen.getByRole("radio", { name: "24h" }));
    expect([last?.chaseFloor, last?.chaseCeiling]).toEqual(["3.2800", "3.4200"]);
    expect(last?.chop?.label).toBe("ranging");
  });

  it("shows only the numbers a trader checks, and the Basis it carries", async () => {
    const user = userEvent.setup();
    render(<Sheet swing={300} />);
    await user.click(await screen.findByRole("radio", { name: "24h" }));
    await user.type(screen.getByLabelText("Step"), "0.02");
    expect(screen.getByText("Clip").nextSibling?.textContent).toBe("100 × 3");
    expect(screen.getByText("Position").nextSibling?.textContent).toBe("700–1,300");
    expect(screen.getByText("Catch-up").nextSibling?.textContent).toBe("none");
    expect(screen.getByText("At an edge").nextSibling?.textContent).toMatch(/^−\$9\.00$/);
    expect(screen.getByText(/3 levels a side: fills come few/)).toBeTruthy();
    expect(screen.getByRole("radio", { name: "¼×" })).toBeTruthy();
    expect(await screen.findByText("3.2697 from MS-0004, run 2")).toBeTruthy();
    expect(screen.queryByText(/The Swing is how far/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "start new" }));
    expect(last?.fresh).toBe(true);
    expect(screen.getByText("starts new")).toBeTruthy();
  });

  it("says a Massager already works the Market instead of a form", async () => {
    act(() => setAlgo({ working: [{ type: "algo", id: "massager", algo_id: "MS-0005", algo_type: "massager", symbol: "LIT", status: "running" }], history: [] }));
    render(<Sheet swing={300} />);
    expect(await screen.findByText(/MS-0005 already works LIT/)).toBeTruthy();
    expect(screen.queryByLabelText("Floor")).toBeNull();
  });
});
