// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SetupsTable } from "@/components/widgets/SetupsTable";
import { api, type SetupBoard } from "@/lib/api";

const BOARD: SetupBoard = {
  built_at: Date.UTC(2026, 10, 7, 12, 1),
  rows: [
    {
      kind: "board",
      market_index: 120,
      symbol: "LIT",
      direction: "up",
      size: 1.1,
      price: 3.39,
      note: "+3.1% 24h · BTC −2.4%",
    },
    {
      kind: "oi_price",
      market_index: 0,
      symbol: "ETH",
      direction: "flat",
      size: 1.6,
      price: 2228,
      note: "OI +8.0% 24h · price −0.4% 24h",
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SetupsTable", () => {
  it("lists each Setup with what it shows, its size and when the board was built", async () => {
    vi.spyOn(api, "setups").mockResolvedValue(BOARD);
    const open = vi.fn();
    render(<SetupsTable symbol="ETH" onSymbolChange={open} />);
    expect(await screen.findByText("Against the board")).toBeTruthy();
    expect(screen.getByText("↑")).toBeTruthy();
    expect(screen.getByText("OI without price")).toBeTruthy();
    expect(screen.getByText("+3.1% 24h · BTC −2.4%")).toBeTruthy();
    expect(screen.getByText("1.6×")).toBeTruthy();
    expect(screen.getByText(/built 12:01 UTC, hourly/)).toBeTruthy();
    fireEvent.click(screen.getByText("LIT"));
    expect(open).toHaveBeenCalledWith("LIT");
  });

  it("says when the board is not built yet, and when it could not load", async () => {
    vi.spyOn(api, "setups").mockResolvedValue({ built_at: null, rows: [] });
    render(<SetupsTable symbol="ETH" />);
    expect(await screen.findByText("The board is built five minutes after the desk starts")).toBeTruthy();
    cleanup();
    vi.spyOn(api, "setups").mockRejectedValue(new Error("down"));
    render(<SetupsTable symbol="ETH" />);
    expect(await screen.findByText("Couldn't load the Setups board")).toBeTruthy();
  });
});
