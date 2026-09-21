import { describe, expect, it } from "vitest";
import {
  nextPosSort,
  pnlAtTrigger,
  pnlFromRoe,
  positionNotional,
  positionsForClose,
  protectCloseSize,
  protectOrderLabel,
  protectTriggersFromOrders,
  protectTriggersLabel,
  roeFromPnl,
  sortPositionRows,
  stopTakeKind,
  triggerFromPnl,
  triggerOnCorrectSide,
  workingProtectOrders,
  type SortablePosition,
} from "@/lib/positionsTable";

function row(
  marketIndex: number,
  opts: Partial<Omit<SortablePosition, "marketIndex">> = {}
): SortablePosition {
  return {
    marketIndex,
    sizeAbs: 1,
    notional: 1000,
    pnl: 0,
    roe: 0,
    ...opts,
  };
}

describe("positionNotional", () => {
  it("uses mark when live", () => {
    expect(positionNotional(2, 50)).toBe(100);
  });

  it("falls back to entry when mark is missing", () => {
    expect(positionNotional(-2, 0, 40)).toBe(80);
  });
});

describe("sortPositionRows", () => {
  const rows = [
    row(1, { notional: 100, roe: 5, pnl: 10, sizeAbs: 1 }),
    row(2, { notional: 500, roe: -2, pnl: -20, sizeAbs: 4 }),
    row(3, { notional: 200, roe: 12, pnl: 40, sizeAbs: 2 }),
  ];

  it("pins the active pair first, then sorts the rest by notional desc", () => {
    const sorted = sortPositionRows(rows, { key: "notional", dir: "desc" }, 1);
    expect(sorted.map((r) => r.marketIndex)).toEqual([1, 2, 3]);
  });

  it("sorts by uPnL % with active still first", () => {
    const sorted = sortPositionRows(rows, { key: "roe", dir: "desc" }, 2);
    expect(sorted.map((r) => r.marketIndex)).toEqual([2, 3, 1]);
  });

  it("sends missing roe to the bottom", () => {
    const mixed = [
      row(1, { roe: 8 }),
      row(2, { roe: null }),
      row(3, { roe: 1 }),
    ];
    expect(
      sortPositionRows(mixed, { key: "roe", dir: "desc" }, null).map((r) => r.marketIndex)
    ).toEqual([1, 3, 2]);
  });
});

describe("positionsForClose", () => {
  const mixed = [
    row(1, { pnl: 12 }),
    row(2, { pnl: -4 }),
    row(3, { pnl: 0 }),
    row(4, { pnl: 0.5 }),
    row(5, { pnl: -0.01 }),
  ];

  it("keeps only positive uPnL for winners", () => {
    expect(positionsForClose(mixed, "winners").map((r) => r.marketIndex)).toEqual([1, 4]);
  });

  it("keeps only negative uPnL for losers", () => {
    expect(positionsForClose(mixed, "losers").map((r) => r.marketIndex)).toEqual([2, 5]);
  });

  it("leaves flats in all, not in W or L", () => {
    expect(positionsForClose(mixed, "all").map((r) => r.marketIndex)).toEqual([1, 2, 3, 4, 5]);
  });

  it("returns empty when nothing matches", () => {
    const flats = [row(1, { pnl: 0 }), row(2, { pnl: 0 })];
    expect(positionsForClose(flats, "winners")).toEqual([]);
    expect(positionsForClose(flats, "losers")).toEqual([]);
    expect(positionsForClose([], "all")).toEqual([]);
  });
});

describe("protectCloseSize", () => {
  it("uses 0 for full so the venue can track the position", () => {
    expect(protectCloseSize(2.5, "full", 9)).toBe(0);
  });

  it("caps a partial at the live size", () => {
    expect(protectCloseSize(2, "partial", 0.5)).toBe(0.5);
    expect(protectCloseSize(2, "partial", 4)).toBe(2);
    expect(protectCloseSize(2, "partial", 0)).toBe(0);
  });
});

describe("triggerOnCorrectSide", () => {
  it("wants a long stop below mark and take-profit above", () => {
    expect(triggerOnCorrectSide("sl", true, 95, 100)).toBe(true);
    expect(triggerOnCorrectSide("sl", true, 105, 100)).toBe(false);
    expect(triggerOnCorrectSide("tp", true, 105, 100)).toBe(true);
    expect(triggerOnCorrectSide("tp", true, 95, 100)).toBe(false);
  });

  it("inverts for a short close", () => {
    expect(triggerOnCorrectSide("sl", false, 105, 100)).toBe(true);
    expect(triggerOnCorrectSide("tp", false, 95, 100)).toBe(true);
    expect(triggerOnCorrectSide("sl", false, 95, 100)).toBe(false);
  });
});

describe("stopTakeKind", () => {
  it("maps venue type strings", () => {
    expect(stopTakeKind("stop-loss")).toBe("sl");
    expect(stopTakeKind("STOP_LOSS_LIMIT")).toBe("sl");
    expect(stopTakeKind("take-profit")).toBe("tp");
    expect(stopTakeKind("4")).toBe("tp");
    expect(stopTakeKind("limit")).toBeNull();
  });
});

describe("workingProtectOrders", () => {
  const orders = [
    { market_index: 1, order_type: "stop-loss", trigger_price: "90" },
    { market_index: 1, order_type: "limit", trigger_price: "" },
    { market_index: 2, order_type: "take-profit", trigger_price: "120" },
  ];

  it("keeps SL/TP on the selected market", () => {
    expect(workingProtectOrders(orders, 1).map((o) => o.order_type)).toEqual(["stop-loss"]);
  });
});

describe("protectOrderLabel", () => {
  it("prefixes SL/TP with the trigger", () => {
    expect(protectOrderLabel("stop-loss", "90")).toBe("SL 90");
    expect(protectOrderLabel("take-profit", "")).toBe("TP");
  });
});

describe("protectTriggersLabel", () => {
  it("shows Lighter-style blanks", () => {
    expect(protectTriggersLabel()).toBe("__ / __");
    expect(protectTriggersLabel("4.9", undefined)).toBe("4.9 / __");
    expect(protectTriggersLabel("4.9", "4.5")).toBe("4.9 / 4.5");
  });
});

describe("protectTriggersFromOrders", () => {
  it("picks the last TP and SL triggers", () => {
    expect(
      protectTriggersFromOrders([
        { order_type: "take-profit", trigger_price: "110" },
        { order_type: "stop-loss", trigger_price: "90" },
        { order_type: "limit", trigger_price: "1" },
      ])
    ).toEqual({ tp: "110", sl: "90" });
  });
});

describe("pnlAtTrigger / triggerFromPnl", () => {
  it("is (trigger - entry) * signed size", () => {
    expect(pnlAtTrigger(100, 2, 110)).toBe(20);
    expect(pnlAtTrigger(100, -2, 90)).toBe(20);
    expect(pnlAtTrigger(100, 2, 90)).toBe(-20);
    expect(triggerFromPnl(100, 2, 20)).toBe(110);
    expect(triggerFromPnl(100, -2, 20)).toBe(90);
    expect(triggerFromPnl(100, 2, -20)).toBe(90);
  });
});

describe("roeFromPnl / pnlFromRoe", () => {
  it("prefers allocated margin, else notional", () => {
    expect(roeFromPnl(20, 50, 200)).toBe(40);
    expect(roeFromPnl(20, 0, 200)).toBe(10);
    expect(pnlFromRoe(40, 50, 200)).toBe(20);
    expect(pnlFromRoe(10, 0, 200)).toBe(20);
  });
});

describe("nextPosSort", () => {
  it("defaults a new column to desc, then toggles", () => {
    expect(nextPosSort({ key: "notional", dir: "desc" }, "roe")).toEqual({
      key: "roe",
      dir: "desc",
    });
    expect(nextPosSort({ key: "roe", dir: "desc" }, "roe")).toEqual({
      key: "roe",
      dir: "asc",
    });
  });
});
