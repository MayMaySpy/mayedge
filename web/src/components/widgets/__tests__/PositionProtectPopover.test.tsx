// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PositionProtectPopover } from "@/components/widgets/PositionProtectPopover";
import type { AlgoState, OpenOrder, Position, StopTakeRequest } from "@/lib/api";

const LONG: Position = {
  market_index: 1,
  symbol: "ETH",
  size: "2",
  entry_price: "100",
  mark_price: "100",
  unrealized_pnl: "0",
  leverage: 5,
  margin_mode: "cross",
  allocated_margin: "40",
};
const SHORT: Position = { ...LONG, size: "-2" };

const LIVE_STOP: OpenOrder = {
  order_index: "77",
  client_order_index: "1000000009",
  market_index: 1,
  symbol: "ETH",
  side: "sell",
  price: "89.1",
  size: "2",
  remaining: "2",
  order_type: "stop-loss",
  reduce_only: true,
  trigger_price: "90",
};

function setup(over: Partial<Parameters<typeof PositionProtectPopover>[0]> = {}) {
  const onPlace = vi.fn(async (_body: StopTakeRequest) => {});
  const onCancel = vi.fn(async (_orderIndex: string) => {});
  render(
    <PositionProtectPopover
      position={LONG}
      mark={100}
      sizeDecimals={2}
      priceDecimals={2}
      tradingEnabled
      busy={false}
      orders={[]}
      onPlace={onPlace}
      onCancel={onCancel}
      {...over}
    />
  );
  return { onPlace, onCancel, user: userEvent.setup() };
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTitle("TP/SL for Position"));
  return screen.getByRole("button", { name: "Submit" }) as HTMLButtonElement;
}

afterEach(cleanup);

describe("PositionProtectPopover", () => {
  it("shows a Planner's exit and edits nothing while Planner owns it", () => {
    setup({ lockedBy: "Planner", orders: [LIVE_STOP] });
    expect(screen.queryByTitle("TP/SL for Position")).toBeNull();
    expect(screen.getByTitle("Planner owns the exit on this Market").textContent).toContain(
      "Planner"
    );
  });

  it("places a market Stop on the whole long Position", async () => {
    const { onPlace, user } = setup();
    const submit = await openDialog(user);
    expect(submit.disabled).toBe(true);

    await user.type(screen.getByLabelText("SL Trigger Price"), "90");
    expect(submit.disabled).toBe(false);
    await user.click(submit);

    expect(onPlace).toHaveBeenCalledTimes(1);
    expect(onPlace).toHaveBeenCalledWith({
      market_index: 1,
      side: "sell",
      size: "0",
      slippage: 0.01,
      sl: { kind: "market", trigger: "90" },
    });
  });

  it("will not place a long's Stop above mark", async () => {
    const { onPlace, user } = setup();
    const submit = await openDialog(user);

    await user.type(screen.getByLabelText("SL Trigger Price"), "110");
    expect(screen.getByText("Trigger must be below mark")).toBeTruthy();
    expect(submit.disabled).toBe(true);
    await user.click(submit);
    expect(onPlace).not.toHaveBeenCalled();
  });

  it("closes a short with buys and wants its Stop above mark", async () => {
    const { onPlace, user } = setup({ position: SHORT });
    const submit = await openDialog(user);

    await user.type(screen.getByLabelText("SL Trigger Price"), "90");
    expect(screen.getByText("Trigger must be above mark")).toBeTruthy();
    expect(submit.disabled).toBe(true);

    await user.clear(screen.getByLabelText("SL Trigger Price"));
    await user.type(screen.getByLabelText("SL Trigger Price"), "110");
    await user.click(submit);
    expect(onPlace).toHaveBeenCalledWith(
      expect.objectContaining({ side: "buy", sl: { kind: "market", trigger: "110" } })
    );
  });

  it("sends both legs, and a limit leg when a limit price is typed", async () => {
    const { onPlace, user } = setup();
    const submit = await openDialog(user);

    await user.type(screen.getByLabelText("TP Trigger Price"), "120");
    await user.type(screen.getByLabelText("SL Trigger Price"), "90");
    const limits = screen.getAllByLabelText("Limit Price");
    await user.type(limits[1], "89.5");
    await user.click(submit);

    expect(onPlace).toHaveBeenCalledWith({
      market_index: 1,
      side: "sell",
      size: "0",
      slippage: 0.01,
      tp: { kind: "market", trigger: "120" },
      sl: { kind: "limit", trigger: "90", price: "89.5" },
    });
  });

  it("leaves out a leg whose trigger is on the wrong side", async () => {
    const { onPlace, user } = setup();
    const submit = await openDialog(user);

    await user.type(screen.getByLabelText("TP Trigger Price"), "80");
    await user.type(screen.getByLabelText("SL Trigger Price"), "90");
    await user.click(submit);

    const body = onPlace.mock.calls[0][0];
    expect(body.sl).toEqual({ kind: "market", trigger: "90" });
    expect(body.tp).toBeUndefined();
  });

  it("does not place while the desk is read-only", async () => {
    const { onPlace, user } = setup({ tradingEnabled: false });
    const submit = await openDialog(user);
    await user.type(screen.getByLabelText("SL Trigger Price"), "90");
    expect(submit.disabled).toBe(true);
    await user.click(submit);
    expect(onPlace).not.toHaveBeenCalled();
  });

  it("keeps the dialog open when the place fails", async () => {
    const { onPlace, user } = setup();
    onPlace.mockRejectedValueOnce(new Error("not placed"));
    const submit = await openDialog(user);
    await user.type(screen.getByLabelText("SL Trigger Price"), "90");
    await user.click(submit);
    expect(onPlace).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Submit" })).toBeTruthy();
  });

  it("cancels a working Stop by its order index", async () => {
    const { onCancel, user } = setup({ orders: [LIVE_STOP] });
    await openDialog(user);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledWith("77");
  });
});

describe("PositionProtectPopover Trail mode", () => {
  const trailSetup = (over: Partial<Parameters<typeof PositionProtectPopover>[0]> = {}) => {
    const onStartTrail = vi.fn(async (_body: Record<string, unknown>) => {});
    const out = setup({ onStartTrail, ...over });
    return { ...out, onStartTrail };
  };
  // The Take Profit section comes first, the Stop Loss second.
  const modeGroup = (i: number) => screen.getAllByLabelText("Fixed or Trail")[i]!;

  it("starts a Trail Stop and names the Stop Ticket it replaces (TS4)", async () => {
    const { onPlace, onStartTrail, user } = trailSetup({ orders: [LIVE_STOP] });
    const submit = await openDialog(user);
    await user.click(within(modeGroup(1)).getByText("Trail"));
    expect(screen.getByText(/Replaces SL 90/)).toBeTruthy();
    expect(screen.getByText(/Stop now 99.00/)).toBeTruthy();
    expect(submit.disabled).toBe(false);
    await user.click(submit);
    expect(onPlace).not.toHaveBeenCalled();
    expect(onStartTrail).toHaveBeenCalledWith({
      distance: "1",
      distance_kind: "pct",
      reference: "mark",
      activation: null,
      kind: "stop",
      market_index: 1,
      start: null,
      slippage: 0.01,
    });
  });

  it("needs an Activation above mark for a long's Trail Take Profit (TT1)", async () => {
    const { onStartTrail, user } = trailSetup();
    const submit = await openDialog(user);
    await user.click(within(modeGroup(0)).getByText("Trail"));
    expect(submit.disabled).toBe(true);
    await user.type(screen.getByLabelText("Activate at"), "99");
    expect(screen.getByText("Activate at must be above mark")).toBeTruthy();
    await user.clear(screen.getByLabelText("Activate at"));
    await user.type(screen.getByLabelText("Activate at"), "105");
    await user.click(submit);
    expect(onStartTrail.mock.calls[0]![0]).toMatchObject({
      kind: "tp",
      activation: "105",
      size_pct: "100",
    });
  });

  it("shows a live Trail Stop as the Position's stop and offers no other", async () => {
    const trail = {
      algo_id: "TR-0001",
      algo_type: "trail",
      status: "running",
      market_index: 1,
      trail: { kind: "stop", trigger: "99" },
    } as unknown as AlgoState;
    const { user } = trailSetup({ trails: [trail] });
    await openDialog(user);
    expect(screen.getByText(/TR-0001 is this Position's stop at 99.00/)).toBeTruthy();
    expect(screen.queryByLabelText("SL Trigger Price")).toBeNull();
  });
});
