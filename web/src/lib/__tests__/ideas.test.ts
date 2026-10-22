import { describe, expect, it } from "vitest";
import type { Idea, JournalTrip } from "@/lib/api.gen";
import {
  blendedR,
  ideaToDraft,
  ideaTrips,
  inZone,
  marketLast,
  pastStop,
  planIssue,
  planReadout,
  priceAtR,
  rAtPrice,
  rNow,
  sortIdeas,
  targetPercents,
  toEntryPct,
  zoneBarMarks,
} from "@/lib/ideas";

function idea(over: Partial<Idea> = {}): Idea {
  return {
    id: "idea-1",
    symbol: "ZRO",
    side: "long",
    status: "watching",
    conviction: 2,
    horizon: "swing",
    thesis: "Unlock overhang gone after the 20th.",
    invalidation: "",
    trigger: "",
    tags: [],
    catalysts: [],
    entry_low: "2.18",
    entry_high: "2.20",
    stop: "2.08",
    targets: [{ price: "2.40", pct: null }],
    planner_ids: [],
    outcome: null,
    review: "",
    created_at: 1_700_000_000_000,
    updated_at: 1_700_000_000_000,
    closed_at: null,
    plan_entry: "2.19",
    r: "0.11",
    r_multiples: ["1.91"],
    ...over,
  };
}

function trip(over: Partial<JournalTrip> = {}): JournalTrip {
  return {
    trip_key: "1:a",
    market_index: 1,
    symbol: "ZRO",
    side: "long",
    open_ts: 1_700_000_100_000,
    close_ts: 1_700_000_200_000,
    size: "1",
    avg_in: "2",
    avg_out: "3",
    pnl: "1",
    fees: "0",
    funding: "0",
    net: "1",
    algo: "manual",
    algo_id: null,
    r: null,
    partial: false,
    partial_reason: null,
    open: false,
    upnl: null,
    note: "",
    tags: [],
    fills: [],
    ...over,
  };
}

describe("Last and the zone", () => {
  it("uses the trade, else the mark, else the mid, and never zero", () => {
    expect(marketLast({ last_trade_price: 2.5, mark_price: 9, mid_price: 8 })).toBe(2.5);
    expect(marketLast({ last_trade_price: null, mark_price: 3.5, mid_price: 4 })).toBe(3.5);
    expect(marketLast({ last_trade_price: 0, mark_price: 0, mid_price: 4 })).toBe(4);
    expect(marketLast({ last_trade_price: null, mark_price: null, mid_price: null })).toBeNull();
    expect(marketLast(null)).toBeNull();
  });

  it("signs to-entry by which way price has to go", () => {
    const row = idea();
    expect(toEntryPct(row, 2.19)).toBe(0);
    expect(inZone(row, 2.19)).toBe(true);
    expect(toEntryPct(row, 2.3)).toBeCloseTo(4.3478, 3);
    expect(toEntryPct(row, 2)).toBeCloseTo(-9, 1);
    const short = idea({ side: "short", stop: "2.30", plan_entry: "2.19", r: "0.11" });
    expect(toEntryPct(short, 2)).toBeCloseTo(9, 1);
    expect(toEntryPct(short, 2.3)).toBeCloseTo(-4.3478, 3);
  });

  it("treats a single price as in zone within 0.25%", () => {
    const row = idea({ entry_low: "2", entry_high: "2", plan_entry: "2", stop: "1", r: "1" });
    expect(inZone(row, 2.004)).toBe(true);
    expect(inZone(row, 2.006)).toBe(false);
    expect(toEntryPct(row, 2.004)).toBe(0);
  });

  it("flags a Watching Idea at or beyond its stop", () => {
    expect(pastStop(idea(), 2.08)).toBe(true);
    expect(pastStop(idea(), 2.09)).toBe(false);
    expect(pastStop(idea({ status: "active" }), 1)).toBe(false);
    expect(pastStop(idea({ side: "short", stop: "2.30" }), 2.3)).toBe(true);
    expect(pastStop(idea({ side: "short", stop: "2.30" }), 2.2)).toBe(false);
  });

  it("measures R now from the plan entry, by side", () => {
    const active = idea({ status: "active", plan_entry: "2", r: "1", stop: "1" });
    expect(rNow(active, 3)).toBe(1);
    expect(rNow(idea({ ...active, side: "short", stop: "3" }), 1)).toBe(1);
    expect(rNow(idea({ status: "watching" }), 3)).toBeNull();
    expect(rNow(active, null)).toBeNull();
  });
});

describe("the Plan", () => {
  it("converts R and price both ways at the Market's decimals", () => {
    expect(priceAtR("2", "1", "long", "2", 2)).toBe("4.00");
    expect(priceAtR("2", "3", "short", "1", 2)).toBe("1.00");
    expect(rAtPrice("2", "1", "4")).toBe("2.00");
    expect(rAtPrice("2.19", "2.08", "2.40")).toBe("1.91");
    expect(rAtPrice("1.78", "1.70", "1.95")).toBe("2.13");
  });

  it("splits missing percents evenly and blends the remainder at 0R", () => {
    expect(targetPercents([])).toEqual([]);
    expect(targetPercents([{ price: "3", pct: null }, { price: "4", pct: null }])).toEqual(["50", "50"]);
    expect(
      targetPercents([
        { price: "3", pct: null },
        { price: "4", pct: null },
        { price: "5", pct: null },
      ]),
    ).toEqual(["33", "33", "34"]);
    expect(targetPercents([{ price: "3", pct: "40" }, { price: "4", pct: null }])).toEqual(["40", "60"]);
    expect(blendedR(["2", "4"], ["50", "50"])).toBe(3);
    expect(blendedR(["2", "4"], ["50", null])).toBe(1);
    expect(blendedR(["2", "4"], [null, null])).toBe(3);
  });

  it("hands a complete Plan to the chart, and the Planner's default when there are no targets", () => {
    const bare = ideaToDraft(idea({ targets: [], r_multiples: [] }), 4);
    expect(bare?.targets).toEqual([
      { r: "2", pct: "50" },
      { r: "3", pct: "50" },
    ]);
    expect(bare?.entry).toBe(2.19);
    expect(ideaToDraft(idea({ plan_entry: null, r: null }), 4)).toBeNull();
    const drafted = ideaToDraft(idea(), 4);
    expect(drafted?.targets).toEqual([{ r: "1.91", pct: "100" }]);
  });
});

describe("trades and the ruler", () => {
  it("keeps Round trips opened while the Idea was open", () => {
    const row = idea({ closed_at: 1_700_000_500_000 });
    const kept = ideaTrips(
      [
        trip({ trip_key: "before", open_ts: 1_699_000_000_000 }),
        trip({ trip_key: "during", open_ts: 1_700_000_100 }),
        trip({ trip_key: "after", open_ts: 1_700_000_500_000 }),
        trip({ trip_key: "other", symbol: "TIA" }),
      ],
      row,
    );
    expect(kept.map((t) => t.trip_key)).toEqual(["during"]);
  });

  it("pads the ruler and keeps marks in price order", () => {
    const bar = zoneBarMarks(
      idea({
        entry_low: "2",
        entry_high: "2",
        stop: "1",
        plan_entry: "2",
        r: "1",
        targets: [{ price: "4", pct: null }],
        r_multiples: ["2.00"],
      }),
      2.5,
      100,
    );
    expect(bar).not.toBeNull();
    const xs = bar!.marks.map((m) => m.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    const stop = bar!.marks.find((m) => m.kind === "stop")!;
    const target = bar!.marks.find((m) => m.kind === "target")!;
    expect(stop.x).toBeGreaterThan(0);
    expect(stop.x).toBeLessThan(10);
    expect(target.x).toBeGreaterThan(90);
    expect(target.x).toBeLessThan(100);
    expect(stop.x).toBeLessThan(target.x);
  });
});

describe("nearest entry", () => {
  it("puts an in-zone Idea ahead of a closer-looking one outside", () => {
    const inside = idea({ id: "in", symbol: "ZRO" });
    const outside = idea({
      id: "out",
      symbol: "TIA",
      entry_low: "10",
      entry_high: "10.1",
      plan_entry: "10.05",
    });
    const markets = new Map([
      ["ZRO", { market_index: 1, symbol: "ZRO", price_decimals: 2, size_decimals: 1, last_trade_price: 2.19 }],
      ["TIA", { market_index: 2, symbol: "TIA", price_decimals: 2, size_decimals: 1, last_trade_price: 10.2 }],
    ]);
    expect(sortIdeas([outside, inside], markets, "entry").map((row) => row.id)).toEqual(["in", "out"]);
  });
});

describe("plan form", () => {
  const zone = { side: "long" as const, low: "2.18", high: "2.20", stop: "2.08", targets: [{ price: "2.40", pct: "" }] };

  it("reads R from the midpoint", () => {
    expect(planReadout(zone)?.r).toBe("0.11");
  });

  it("refuses a long stop above the zone", () => {
    expect(planIssue({ ...zone, stop: "3" })).toEqual({
      field: "stop",
      message: "A long stop sits below the entry.",
    });
  });
});
