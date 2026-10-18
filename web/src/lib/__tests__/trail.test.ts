import { describe, expect, it } from "vitest";
import type { AlgoBook, AlgoState, OpenOrder } from "@/lib/api";
import {
  defaultTrailExitDraft,
  liveTrailStop,
  stopTicketsReplaced,
  trailActivationReached,
  trailBody,
  trailDistanceProblem,
  trailExitProblem,
  trailPhase,
  trailTriggerAt,
} from "@/lib/trail";

describe("trail trigger", () => {
  it("sits the distance behind the best price, rounded away from it (F2, F3)", () => {
    // The ZRO example in docs/trail-rules.md.
    expect(trailTriggerAt("sell", { distance: "1.5", distanceKind: "pct" }, 2.25, 4)).toBe(2.2162);
    expect(trailTriggerAt("buy", { distance: "1", distanceKind: "price" }, 100, 2)).toBe(101);
    expect(trailTriggerAt("buy", { distance: "1", distanceKind: "pct" }, 101.23, 2)).toBe(102.25);
  });

  it("refuses a distance under two ticks (S3)", () => {
    expect(trailDistanceProblem({ distance: "0.01", distanceKind: "price" }, 100, 2)).toMatch(/2 ticks/);
    expect(trailDistanceProblem({ distance: "0.02", distanceKind: "price" }, 100, 2)).toBeNull();
    expect(trailDistanceProblem({ distance: "", distanceKind: "pct" }, 100, 2)).toMatch(/distance/);
  });

  it("activates on the favourable side (F5)", () => {
    expect(trailActivationReached("sell", 105, 105)).toBe(true);
    expect(trailActivationReached("sell", 104, 105)).toBe(false);
    expect(trailActivationReached("buy", 94, 95)).toBe(true);
  });
});

describe("trail exit drafts", () => {
  const long = { closeSide: "sell" as const, mark: 100, liq: 80 };
  it("needs an Activation past mark on a Take Profit (TT1)", () => {
    const d = defaultTrailExitDraft();
    expect(trailExitProblem("tp", d, long.closeSide, long.mark, long.liq, 2)).toMatch(/Activate/);
    expect(trailExitProblem("tp", { ...d, activation: "99" }, "sell", 100, 80, 2)).toMatch(/above mark/);
    expect(trailExitProblem("tp", { ...d, activation: "105" }, "sell", 100, 80, 2)).toBeNull();
  });

  it("checks a Stop's start against mark and the Liquidation price (S3)", () => {
    const d = defaultTrailExitDraft();
    expect(trailExitProblem("stop", { ...d, start: "101" }, "sell", 100, 80, 2)).toMatch(/below mark/);
    expect(trailExitProblem("stop", { ...d, start: "79" }, "sell", 100, 80, 2)).toMatch(/Liquidation/);
    expect(trailExitProblem("stop", { ...d, start: "95" }, "sell", 100, 80, 2)).toBeNull();
  });

  it("builds the start body", () => {
    expect(trailBody({ ...defaultTrailExitDraft(), activation: "" }, { kind: "stop" })).toEqual({
      distance: "1",
      distance_kind: "pct",
      reference: "mark",
      activation: null,
      kind: "stop",
    });
  });
});

describe("trail state", () => {
  const algo = (patch: Partial<AlgoState>): AlgoState =>
    ({
      algo_type: "trail",
      status: "running",
      market_index: 1,
      trail: {
        kind: "stop",
        side: "sell",
        qty: "0",
        reference: "mark",
        distance: "1",
        distance_kind: "pct",
        activation: null,
        floor: "99",
        active: true,
        best: "100",
        trigger: "99",
        venue_trigger: "99",
        last_move_ms: null,
        fired_at: null,
        fired_price: null,
        deadline_ms: null,
        following: true,
        backstop: false,
      },
      ...patch,
    }) as AlgoState;

  it("names its phase", () => {
    expect(trailPhase(algo({}))).toBe("following");
    const a = algo({});
    expect(trailPhase({ ...a, trail: { ...a.trail!, active: false } })).toBe("waiting");
    expect(trailPhase({ ...a, trail: { ...a.trail!, following: false } })).toBe("not following");
    expect(trailPhase(algo({ status: "paused" }))).toBe("paused");
  });

  it("finds the live Trail Stop on a Market", () => {
    const book: AlgoBook = { working: [algo({}), algo({ market_index: 2 })], history: [] };
    expect(liveTrailStop(book, 1)?.market_index).toBe(1);
    expect(liveTrailStop(book, 3)).toBeNull();
  });

  it("replaces only Stop Tickets on the closing side (TS4)", () => {
    const row = (o: Partial<OpenOrder>): OpenOrder =>
      ({ market_index: 1, side: "sell", order_type: "stop-loss", client_order_index: "1000000001", ...o }) as OpenOrder;
    const orders = [
      row({ order_index: "1" }),
      row({ order_index: "2", order_type: "take-profit" }),
      row({ order_index: "3", client_order_index: "12000000001" }),
      row({ order_index: "4", side: "buy" }),
    ];
    const got = stopTicketsReplaced(
      orders,
      1,
      "sell",
      (coi) => Number(coi) >= 7e9,
      (t) => t.includes("stop")
    );
    expect(got.map((o) => o.order_index)).toEqual(["1"]);
  });
});
