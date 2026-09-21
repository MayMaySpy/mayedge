import { describe, expect, it } from "vitest";
import {
  depthBarWidths,
  sideMaxTotal,
  toDepthRows,
  walkMovePct,
  walkNotional,
} from "@/lib/orderBookDepth";

describe("toDepthRows", () => {
  it("accumulates total from the best level outward", () => {
    const rows = toDepthRows(
      [
        { price: "10", size: "2" },
        { price: "11", size: "3" },
        { price: "12", size: "0" },
        { price: "13", size: "5" },
      ],
      8
    );
    expect(rows.map((r) => r.total)).toEqual([2, 5, 10]);
    expect(sideMaxTotal(rows)).toBe(10);
  });
});

describe("depthBarWidths", () => {
  it("matches Lighter: outer is total/max, inner is size/total", () => {
    expect(depthBarWidths(6.411, 6.411, 285.1507).cumPct).toBeCloseTo(2.248, 2);
    expect(depthBarWidths(6.411, 6.411, 285.1507).sizePct).toBeCloseTo(100, 5);
    expect(depthBarWidths(25, 285.1507, 285.1507).cumPct).toBeCloseTo(100, 5);
    expect(depthBarWidths(25, 285.1507, 285.1507).sizePct).toBeCloseTo(8.767, 2);
  });
});

describe("walkNotional", () => {
  const asks = [
    { price: "101", size: "50" },
    { price: "102", size: "50" },
  ];
  const bids = [
    { price: "99", size: "50" },
    { price: "98", size: "50" },
  ];

  it("fills a buy at one ask and reports +1% vs mid 100", () => {
    const walk = walkNotional(asks, 2000);
    expect(walk).toEqual({
      filledUsd: 2000,
      filledSize: 2000 / 101,
      avgPrice: 101,
      worstPrice: 101,
      complete: true,
      lastIndex: 0,
      lastFrac: 2000 / (101 * 50),
    });
    expect(walkMovePct(walk, 100)).toBeCloseTo(1, 10);
  });

  it("fills a sell at one bid and reports -1% vs mid 100", () => {
    const walk = walkNotional(bids, 2000);
    expect(walk?.worstPrice).toBe(99);
    expect(walk?.complete).toBe(true);
    expect(walkMovePct(walk, 100)).toBeCloseTo(-1, 10);
  });

  it("crosses into the next level and weights the average", () => {
    const walk = walkNotional(asks, 5050 + 1020);
    expect(walk?.complete).toBe(true);
    expect(walk?.worstPrice).toBe(102);
    expect(walk?.lastIndex).toBe(1);
    expect(walk?.filledSize).toBeCloseTo(50 + 10, 8);
    expect(walk?.avgPrice).toBeCloseTo((5050 + 1020) / 60, 8);
  });

  it("returns incomplete when the side cannot fill the notional", () => {
    const walk = walkNotional(asks, 20_000);
    expect(walk?.complete).toBe(false);
    expect(walkMovePct(walk, 100)).toBeNull();
  });

  it("returns null for empty book or non-positive usd", () => {
    expect(walkNotional([], 1000)).toBeNull();
    expect(walkNotional(asks, 0)).toBeNull();
  });
});
