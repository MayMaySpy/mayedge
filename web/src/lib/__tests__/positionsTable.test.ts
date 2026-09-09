import { describe, expect, it } from "vitest";
import {
  nextPosSort,
  positionNotional,
  sortPositionRows,
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
