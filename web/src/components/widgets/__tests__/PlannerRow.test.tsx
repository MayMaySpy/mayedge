// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlannerRow } from "@/components/widgets/planner/PlannerRow";
import type { AlgoState } from "@/lib/api";

function planner(phase: "entering" | "managing"): AlgoState {
  return {
    type: "algo",
    id: "planner",
    algo_type: "planner",
    algo_id: "PL-0001",
    status: "running",
    market_index: 1,
    symbol: "ETH",
    side: "buy",
    qty: "2",
    filled: "0.6",
    params_json: { entry_type: "chase", stop: "95", targets: [] },
    planner: {
      phase,
      plan: null,
      roles: {},
      entry_filled: "0.6",
      expected_size: "0.6",
      stop_trigger: "95",
      breakeven_done: false,
      entry_deadline_ms: null,
      clip_roles: {},
    },
  };
}

afterEach(cleanup);

describe("PlannerRow", () => {
  it("ends a working entry with Protect now", async () => {
    const onProtect = vi.fn();
    render(<PlannerRow algo={planner("entering")} busy={false} tradingEnabled onProtect={onProtect} />);
    expect(screen.getByText("Chasing 0.6 / 2")).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "Protect now" }));
    expect(onProtect).toHaveBeenCalledTimes(1);
  });

  it("has no Protect now once the entry is over", () => {
    render(<PlannerRow algo={planner("managing")} busy={false} tradingEnabled onProtect={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Protect now" })).toBeNull();
  });
});
