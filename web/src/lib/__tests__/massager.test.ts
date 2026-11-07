import { describe, expect, it } from "vitest";
import {
  massagerPreview,
  massagerRefusal,
  massagerRowFacts,
  type MassagerInput,
} from "@/lib/massager";

// The LIT example from docs/massager-rules.md.
const LIT: MassagerInput = {
  bandLow: 3.2,
  bandHigh: 3.5,
  swing: 300,
  clip: 100,
  position: 1000,
  mid: 3.42,
  tick: 0.0001,
  sizeStep: 1,
  minQty: 10,
  makerBps: 0,
};

describe("massager preview (massager-rules MS1–MS8)", () => {
  it("cuts the Band into even levels around the Center", () => {
    const p = massagerPreview(LIT)!;
    expect(p.levels).toBe(3);
    expect(p.center).toBeCloseTo(3.35, 10);
    expect(p.step).toBeCloseTo(0.05, 10);
    expect(p.prices.map((x) => x.toFixed(4))).toEqual([
      "3.2000",
      "3.2500",
      "3.3000",
      "3.3500",
      "3.4000",
      "3.4500",
      "3.5000",
    ]);
    expect([p.positionLow, p.positionHigh]).toEqual([700, 1300]);
    expect(p.perRoundTrip).toBeCloseTo(5, 10);
  });

  it("owes a catch-up for the levels price has passed", () => {
    expect(massagerPreview(LIT)!.catchUp).toEqual({ side: "sell", qty: 100, level: 1 });
    expect(massagerPreview({ ...LIT, mid: 3.21 })!.catchUp).toEqual({
      side: "buy",
      qty: 200,
      level: -2,
    });
    expect(massagerPreview({ ...LIT, mid: 3.36 })!.catchUp.side).toBeNull();
  });

  it("works a short Core the same way: sells above the Center", () => {
    const p = massagerPreview({ ...LIT, position: -1000 })!;
    expect(p.catchUp.side).toBe("sell");
    expect([p.positionLow, p.positionHigh]).toEqual([-1300, -700]);
  });

  it("refuses in the backend's words", () => {
    expect(massagerRefusal({ ...LIT, position: 0 })).toBe("A Massager needs an open Position");
    expect(massagerRefusal({ ...LIT, mid: 3.6 })).toBe("Price is outside the Band");
    expect(massagerRefusal({ ...LIT, swing: 250 })).toBe(
      "The Swing must be a whole number of Clips"
    );
    expect(massagerRefusal({ ...LIT, swing: 8, clip: 4 })).toBe(
      "The Clip is under the venue minimum"
    );
    expect(massagerRefusal({ ...LIT, position: 300 })).toBe(
      "The Swing must be smaller than the Core"
    );
    expect(massagerRefusal({ ...LIT, makerBps: 80 })).toMatch(/does not clear the fees/);
    expect(massagerRefusal(LIT)).toBeNull();
  });
});

describe("massager working row (massager-rules MS20)", () => {
  it("reads the Position and its range off the desk's snapshot", () => {
    expect(
      massagerRowFacts({ core: "1000", lean: "-100", position: "900", qty: "300", captured_pnl: "5" })
    ).toEqual({
      core: 1000,
      lean: -100,
      position: 900,
      positionLow: 700,
      positionHigh: 1300,
      captured: 5,
    });
    expect(massagerRowFacts({ core: "-1000", lean: "100", qty: "300" }).position).toBe(-900);
  });
});
