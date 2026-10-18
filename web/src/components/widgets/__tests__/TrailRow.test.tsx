// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TrailRow } from "@/components/widgets/trail/TrailRow";
import type { AlgoState, TrailRuntime } from "@/lib/api";

const RT: TrailRuntime = {
  kind: "stop",
  side: "sell",
  qty: "0",
  reference: "mark",
  distance: "1.5",
  distance_kind: "pct",
  activation: null,
  floor: "95",
  active: true,
  best: "104",
  trigger: "102.44",
  venue_trigger: "102.44",
  last_move_ms: null,
  fired_at: null,
  fired_price: null,
  deadline_ms: null,
  following: true,
  backstop: false,
};

function row(rt: Partial<TrailRuntime> = {}, over: Partial<AlgoState> = {}): AlgoState {
  return {
    algo_id: "TR-0001",
    algo_type: "trail",
    status: "running",
    symbol: "ETH",
    market_index: 1,
    trail: { ...RT, ...rt },
    ...over,
  } as AlgoState;
}

afterEach(cleanup);

describe("TrailRow", () => {
  it("shows what a Trail Stop follows and where its stop is", () => {
    render(<TrailRow algo={row()} busy={false} tradingEnabled />);
    expect(screen.getByText("Trail Stop")).toBeTruthy();
    expect(screen.getByText("following")).toBeTruthy();
    expect(screen.getByText("1.5% Mark")).toBeTruthy();
    expect(screen.getByText("102.44")).toBeTruthy();
  });

  it("says when it is not following", () => {
    render(<TrailRow algo={row({ following: false })} busy={false} tradingEnabled />);
    expect(screen.getByText("not following")).toBeTruthy();
  });

  it("offers Keep stop and Cancel stop for a Trail Stop (S5)", async () => {
    const onStop = vi.fn();
    const user = userEvent.setup();
    render(<TrailRow algo={row()} busy={false} tradingEnabled onStop={onStop} />);
    await user.click(screen.getByRole("button", { name: /^Stop$/ }));
    await user.click(await screen.findByText(/Keep stop/));
    expect(onStop).toHaveBeenCalledWith(true);
  });

  it("stops a Trail Entry with one button", async () => {
    const onStop = vi.fn();
    const user = userEvent.setup();
    render(
      <TrailRow
        algo={row({ kind: "entry", side: "buy", qty: "1", active: false, activation: "95", trigger: null })}
        busy={false}
        tradingEnabled
        onStop={onStop}
      />
    );
    expect(screen.getByText("waiting")).toBeTruthy();
    expect(screen.getByText(/starts at/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledWith(false);
  });
});
