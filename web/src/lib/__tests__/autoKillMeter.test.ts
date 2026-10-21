import { describe, expect, it } from "vitest";
import type { Position } from "@/lib/api";
import { autoKillMeter, autoKillUpnl } from "@/lib/autoKillMeter";

function pos(size: string, entry: string, mark: string, upnl = "0"): Position {
  return {
    market_index: 1,
    symbol: "ETH",
    size,
    entry_price: entry,
    mark_price: mark,
    unrealized_pnl: upnl,
    leverage: 5,
    margin_mode: "cross",
  };
}

describe("autoKillUpnl", () => {
  it("sums (mark − entry) × size, signed by side, like the backend", () => {
    // Long 2 from 100 to 90: −20. Short 1 from 50 to 45: +5.
    expect(autoKillUpnl([pos("2", "100", "90"), pos("-1", "50", "45")])).toBeCloseTo(-15);
  });

  it("falls back to the venue's uPnL without a mark or an entry", () => {
    expect(autoKillUpnl([pos("2", "0", "90", "-7.5"), pos("1", "100", "", "3")])).toBeCloseTo(-4.5);
  });

  it("is zero when flat", () => {
    expect(autoKillUpnl([])).toBe(0);
  });
});

describe("autoKillMeter", () => {
  it("measures the way to the loss floor", () => {
    const m = autoKillMeter(-20, 80, null);
    expect(m.lossShare).toBeCloseTo(0.25);
    expect(m.toLoss).toBeCloseTo(60);
    expect(m.profitShare).toBeNull();
    expect(m.toProfit).toBeNull();
  });

  it("measures the way to the profit target and leaves the floor untouched", () => {
    const m = autoKillMeter(150, 80, 200);
    expect(m.lossShare).toBe(0);
    expect(m.toLoss).toBeCloseTo(230);
    expect(m.profitShare).toBeCloseTo(0.75);
    expect(m.toProfit).toBeCloseTo(50);
  });

  it("stops at the limit once uPnL is past it", () => {
    const m = autoKillMeter(-120, 80, null);
    expect(m.lossShare).toBe(1);
    expect(m.toLoss).toBe(0);
  });

  it("ignores a limit that is not positive", () => {
    const m = autoKillMeter(-20, 0, null);
    expect(m.lossShare).toBeNull();
  });
});
