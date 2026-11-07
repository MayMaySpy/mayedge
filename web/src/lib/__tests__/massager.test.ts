import { describe, expect, it } from "vitest";
import {
  closedAtr,
  lastAtr,
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
  step: 0.05,
  position: 1000,
  mid: 3.42,
  tick: 0.0001,
  sizeStep: 1,
  minQty: 10,
  makerBps: 0,
};

describe("massager preview (massager-rules MS1–MS8)", () => {
  it("steps out from the Center and splits the Swing over the levels that fit", () => {
    const p = massagerPreview(LIT)!;
    expect(p.levels).toBe(3);
    expect([p.clip, p.swing]).toEqual([100, 300]);
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

  it("derives the Clip from a typed Step, down to the size step (MS3)", () => {
    const tight = massagerPreview({ ...LIT, step: 0.02 })!;
    expect([tight.levels, tight.clip, tight.swing]).toEqual([7, 42, 294]);
    expect(tight.perRoundTrip).toBeCloseTo(0.84, 10);
    const odd = massagerPreview({ ...LIT, step: 0.04 })!;
    expect(odd.prices.map((x) => x.toFixed(4))).toEqual([
      "3.2300",
      "3.2700",
      "3.3100",
      "3.3500",
      "3.3900",
      "3.4300",
      "3.4700",
    ]);
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
    expect(massagerRefusal({ ...LIT, step: 0 })).toBe("Set the Swing and the Step");
    expect(massagerRefusal({ ...LIT, step: 0.16 })).toBe("The Step is wider than half the Band");
    expect(massagerRefusal({ ...LIT, step: 0.005, swing: 270 })).toBe(
      "The Clip comes out under the venue minimum: widen the Step or raise the Swing"
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

describe("massager Step presets (massager-rules MS19)", () => {
  it("reads the last ATR off the candles, Wilder-smoothed", () => {
    const flat = Array.from({ length: 20 }, () => ({ high: 3.3, low: 3.2, close: 3.25 }));
    expect(lastAtr(flat)).toBeCloseTo(0.1, 10);
    expect(lastAtr(flat.slice(0, 5))).toBeNull();
  });

  it("leaves out the candle that is still open (MS21)", () => {
    const hour = 3600;
    const bars = Array.from({ length: 20 }, (_, i) => ({
      time: i * hour,
      high: 3.3,
      low: 3.2,
      close: 3.25,
    }));
    const now = 20 * hour * 1000 + 1;
    const wild = [...bars, { time: 20 * hour, high: 4, low: 3, close: 3.5 }];
    expect(closedAtr(wild, "1h", now)).toBeCloseTo(0.1, 10);
  });
});
