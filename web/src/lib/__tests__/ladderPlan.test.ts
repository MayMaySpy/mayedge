import { describe, expect, it } from "vitest";
import { buildLadderPlan, createLadderRng } from "@/lib/ladderPlan";

describe("ladder plan preview", () => {
  it("builds even buy rungs that sum to size", () => {
    const plan = buildLadderPlan({
      side: "buy",
      qty: 10,
      priceFrom: 100,
      priceTo: 90,
      orders: 5,
      tick: 0.1,
      qtyStep: 0.01,
      minQty: 0.1,
    });
    expect("error" in plan).toBe(false);
    if ("error" in plan) return;
    expect(plan.orders).toHaveLength(5);
    expect(plan.qty).toBeCloseTo(10, 8);
    expect(plan.orders[0].price).toBeCloseTo(100, 8);
    expect(plan.orders[4].price).toBeCloseTo(90, 8);
    expect(plan.avgEntry).toBeGreaterThan(90);
    expect(plan.avgEntry).toBeLessThan(100);
  });

  it("matches the shared LCG first draws", () => {
    const rng = createLadderRng(7);
    expect(rng.uniform(-0.2, 0.2)).toBeCloseTo(-0.10448766406625509, 12);
    expect(rng.uniform(-0.2, 0.2)).toBeCloseTo(0.16539730587974194, 12);
  });

  it("jitters sizes with variance and a seed", () => {
    const plan = buildLadderPlan({
      side: "buy",
      qty: 10,
      priceFrom: 100,
      priceTo: 90,
      orders: 5,
      tick: 0.1,
      qtyStep: 0.01,
      minQty: 0.01,
      sizeVarPct: 20,
      priceVarPct: 10,
      seed: 7,
    });
    expect("error" in plan).toBe(false);
    if ("error" in plan) return;
    expect(plan.qty).toBeCloseTo(10, 8);
    expect(plan.orders[0].qty).toBeCloseTo(1.79, 2);
    const sizes = new Set(plan.orders.map((o) => o.qty.toFixed(4)));
    expect(sizes.size).toBeGreaterThan(1);
  });

  it("puts more size at low prices when skewed low", () => {
    const even = buildLadderPlan({
      side: "buy",
      qty: 10,
      priceFrom: 100,
      priceTo: 90,
      orders: 5,
      tick: 0.1,
      qtyStep: 0.01,
      minQty: 0.01,
    });
    const low = buildLadderPlan({
      side: "buy",
      qty: 10,
      priceFrom: 100,
      priceTo: 90,
      orders: 5,
      tick: 0.1,
      qtyStep: 0.01,
      minQty: 0.01,
      sizeSkew: -1,
    });
    expect("error" in even || "error" in low).toBe(false);
    if ("error" in even || "error" in low) return;
    const evenHi = even.orders[0].qty;
    const evenLo = even.orders[even.orders.length - 1].qty;
    const lowHi = low.orders[0].qty;
    const lowLo = low.orders[low.orders.length - 1].qty;
    expect(lowLo).toBeGreaterThan(lowHi);
    expect(lowLo).toBeGreaterThan(evenLo);
    expect(lowHi).toBeLessThan(evenHi);
  });

  it("puts more size at high prices when skewed high", () => {
    const high = buildLadderPlan({
      side: "buy",
      qty: 10,
      priceFrom: 100,
      priceTo: 90,
      orders: 5,
      tick: 0.1,
      qtyStep: 0.01,
      minQty: 0.01,
      sizeSkew: 1,
    });
    expect("error" in high).toBe(false);
    if ("error" in high) return;
    expect(high.orders[0].qty).toBeGreaterThan(high.orders[high.orders.length - 1].qty);
  });

  it("checks each order against the quote minimum at its own price", () => {
    // MON: $10 minimum, 250 base. 1142 an order is enough at 0.02 but not near 0.005.
    const mon = { side: "buy" as const, priceFrom: 0.01, priceTo: 0.005, tick: 0.00001, qtyStep: 0.1, minQty: 250, minQuote: 10 };
    const refused = buildLadderPlan({ ...mon, qty: 40000, orders: 35 });
    expect("error" in refused && refused.error).toMatch(/^The order at 0\.00\d+ must be ≥ [\d.]+ \(the venue's \$10 minimum\)/);
    const ok = buildLadderPlan({ ...mon, qty: 40000, orders: 8 });
    expect("orders" in ok && ok.orders.every((o) => o.qty * o.price >= 10 - 1e-9)).toBe(true);
  });
});

