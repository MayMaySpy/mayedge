import { describe, expect, it } from "vitest";
import type { AlgoBook, AlgoState } from "@/lib/api";
import { orderNotice } from "@/lib/orderNotice";
import {
  canProtectNow,
  defaultPlannerForm,
  formFromPlanner,
  livePlannerFor,
  plannerBody,
  plannerClipLabel,
  plannerFormBlock,
  plannerPhaseLabel,
  replacedLine,
  rLabel,
  runnerPct,
  signedPct,
  stepGapPct,
  stepReached,
  stopLabel,
} from "@/lib/plannerPlan";

const form = { ...defaultPlannerForm("buy"), entryPrice: "100", stop: "95" };

function planner(over: Partial<AlgoState> = {}): AlgoState {
  return {
    type: "algo",
    id: "planner",
    algo_type: "planner",
    algo_id: "PL-0001",
    status: "running",
    market_index: 1,
    symbol: "ETH",
    side: "buy",
    params_json: {
      stop: "95",
      breakeven: true,
      targets: [{ kind: "r", value: "2", pct: "50" }],
    },
    planner: {
      phase: "managing",
      plan: null,
      roles: {},
      entry_filled: "2",
      expected_size: "2",
      stop_trigger: "95",
      breakeven_done: false,
      entry_deadline_ms: null,
      clip_roles: { "11000000001": "entry", "11000000002": "stop", "11000000003": "tp1" },
    },
    ...over,
  };
}

describe("planner form", () => {
  it("rides what no target closes on the stop", () => {
    expect(runnerPct([{ kind: "r", value: "2", pct: "33", order: "limit" }, { kind: "r", value: "3", pct: "33", order: "limit" }])).toBe(34);
    expect(runnerPct(defaultPlannerForm().targets)).toBe(0);
  });

  it("names the first thing missing", () => {
    expect(plannerFormBlock({ ...form, stop: "" }, "enter")).toBe("Set a stop");
    expect(plannerFormBlock({ ...form, entryPrice: "" }, "enter")).toBe("Set the entry price");
    expect(plannerFormBlock({ ...form, entryPrice: "", entryType: "market" }, "enter")).toBeNull();
    expect(plannerFormBlock({ ...form, entryPrice: "" }, "attach")).toBeNull();
    expect(plannerFormBlock({ ...form, targets: [] }, "enter")).toBe("Add a target, or trail the stop");
    expect(
      plannerFormBlock(
        { ...form, targets: [{ kind: "r", value: "2", pct: "60", order: "limit" }, { kind: "r", value: "3", pct: "50", order: "limit" }] },
        "enter"
      )
    ).toBe("Targets add up to more than 100%");
  });

  it("sends a size or a risk %, never both, and nothing an Attach does not use", () => {
    const enter = plannerBody(form, { mode: "enter", marketIndex: 1, slippage: 0.01 });
    expect((enter.targets as { order: string }[]).map((t) => t.order)).toEqual(["limit", "limit"]);
    expect(enter).toMatchObject({
      mode: "enter",
      entry_price: "100",
      risk_pct: "1",
      size: null,
      stop_steps: "breakeven",
    });
    const sized = plannerBody({ ...form, sizeMode: "size", size: "2" }, { mode: "enter", marketIndex: 1, slippage: 0.01 });
    expect(sized).toMatchObject({ size: "2", risk_pct: null });
    const attach = plannerBody(form, { mode: "attach", marketIndex: 1, slippage: 0.01 });
    expect(attach).toMatchObject({ entry_price: null, size: null, risk_pct: null, expiry_min: null });
  });

  it("sends a Trail entry, a Trail stop and a Trail target (E9, M10, P9)", () => {
    const form = {
      ...defaultPlannerForm("buy"),
      stop: "95",
      entryType: "trail" as const,
      entryTrail: { distance: "1", distanceKind: "price" as const, activation: "98" },
      trailStop: { start: "target" as const, after: "1", atR: "2", distance: "1", unit: "r" as const },
      reference: "last" as const,
      targets: [
        { kind: "r" as const, value: "1", pct: "50", order: "trigger" as const },
        { kind: "r" as const, value: "2", pct: "50", order: "trail" as const, trailDistance: "0.5", trailUnit: "pct" as const },
      ],
      expiryMin: "30",
    };
    expect(plannerFormBlock(form, "enter")).toBeNull();
    const body = plannerBody(form, { mode: "enter", marketIndex: 1, slippage: 0.01 });
    expect(body).toMatchObject({
      entry_type: "trail",
      entry_price: null,
      entry_trail: { distance: "1", distance_kind: "price", activation: "98" },
      trail_stop: { start: "target", after: 1, at_r: null, distance: "1", unit: "r" },
      reference: "last",
      expiry_min: 30,
    });
    expect((body.targets as Record<string, unknown>[])[1]).toMatchObject({
      order: "trail",
      trail_distance: "0.5",
      trail_unit: "pct",
    });
  });

  it("allows no targets only with a Trail stop (P5)", () => {
    const form = { ...defaultPlannerForm("buy"), entryPrice: "100", stop: "95", targets: [] };
    expect(plannerFormBlock(form, "enter")).toMatch(/trail the stop/);
    const trailing = { ...form, trailStop: { ...form.trailStop, start: "last" as const } };
    expect(plannerFormBlock(trailing, "enter")).toBeNull();
    const bad = { ...trailing, trailStop: { ...trailing.trailStop, start: "target" as const, after: "1" } };
    expect(plannerFormBlock(bad, "enter")).toMatch(/Pick the target/);
  });

  it("re-plans from the running Planner", () => {
    const f = formFromPlanner(planner());
    expect(f.stop).toBe("95");
    // Saved without a type: a Trigger (P9).
    expect(f.targets).toEqual([{ kind: "r", value: "2", pct: "50", order: "trigger" }]);
    expect(f.stopSteps).toBe("breakeven");
    const ladder = planner({ params_json: { stop: "95", stop_steps: "ladder", targets: [] } });
    expect(formFromPlanner(ladder).stopSteps).toBe("ladder");
    const off = planner({ params_json: { stop: "95", breakeven: false, targets: [] } });
    expect(formFromPlanner(off).stopSteps).toBe("off");
  });
});

describe("planner labels", () => {
  it("finds the live Planner on a Market", () => {
    const book: AlgoBook = { working: [planner(), planner({ algo_id: "PL-0002", market_index: 2, status: "done" })], history: [] };
    expect(livePlannerFor(book, 1)?.algo_id).toBe("PL-0001");
    expect(livePlannerFor(book, 2)).toBeUndefined();
  });

  it("names each Clip by its role", () => {
    const algo = planner();
    expect(plannerClipLabel(algo, "11000000001")).toBe("Entry");
    expect(plannerClipLabel(algo, "11000000002")).toBe("Stop");
    expect(plannerClipLabel(algo, 11000000003)).toBe("TP1");
    expect(plannerClipLabel(algo, "1")).toBeNull();
    const at_be = planner({ planner: { ...algo.planner!, breakeven_done: true } });
    expect(plannerClipLabel(at_be, "11000000002")).toBe("BE stop");
    expect(plannerPhaseLabel(at_be)).toBe("At breakeven");
  });

  it("names where the stop has stepped to", () => {
    const base = planner();
    const plan = {
      side: "buy" as const,
      entry: "100",
      stop: "95",
      r: "5",
      size: "5",
      targets: [
        { index: 1, price: "105", qty: "2", pct: "40", r: "1", move_pct: "5" },
        { index: 2, price: "110", qty: "2", pct: "40", r: "2", move_pct: "10" },
      ],
      runner: "1",
      risk_usd: "25",
      risk_pct: "0.25",
      breakeven: "100",
      stop_pct: "-5",
      warnings: [],
      steps: [
        { after: 1, price: "100", to: "breakeven" },
        { after: 2, price: "105", to: "tp1" },
      ],
    };
    const at = (n: number) =>
      planner({ planner: { ...base.planner!, plan, steps_done: n, breakeven_done: n >= 1 } });
    expect(stepReached(at(0))).toBeNull();
    expect(stopLabel(at(1))).toBe("BE stop");
    expect(stopLabel(at(2))).toBe("Stop at TP1");
    expect(plannerPhaseLabel(at(2))).toBe("At TP1");
    expect(stepGapPct(plan, 2, "105")).toBe("−4.55%");
  });

  it("formats from entry", () => {
    expect(signedPct("9.6238")).toBe("+9.62%");
    expect(signedPct("-4.8")).toBe("−4.80%");
    expect(rLabel("2.000")).toBe("2R");
  });

  it("names the Tickets an Attach replaces", () => {
    expect(replacedLine([])).toBeNull();
    expect(
      replacedLine([
        {
          order_index: "77",
          client_order_index: "9",
          market_index: 1,
          symbol: "ETH",
          side: "sell",
          price: "89",
          size: "0",
          remaining: "0",
          order_type: "stop-loss",
          reduce_only: true,
          trigger_price: "90",
        },
      ])
    ).toBe("Replaces Stop 90");
  });

  it("toasts a Planner start", () => {
    expect(orderNotice({ kind: "planner", side: "sell", size: "2", symbol: "ETH", status: "active" })).toEqual({
      title: "Planner started",
      description: "Short 2 ETH",
      tone: "ask",
    });
  });
});

describe("planner Chase entry", () => {
  const chase = {
    ...defaultPlannerForm("buy"),
    entryType: "chase" as const,
    stop: "95",
    entryChase: { low: "99", high: "100.5", offsetBps: "4", clip: "1" },
  };

  it("needs a band whose low is under its high", () => {
    expect(plannerFormBlock({ ...chase, entryChase: { ...chase.entryChase, low: "" } }, "enter")).toBe(
      "Set the Chase band"
    );
    expect(plannerFormBlock({ ...chase, entryChase: { ...chase.entryChase, low: "101" } }, "enter")).toBe(
      "The band's low must be under its high"
    );
    expect(plannerFormBlock(chase, "enter")).toBeNull();
  });

  it("sends the band, offset and clip, and no entry price", () => {
    const body = plannerBody({ ...chase, expiryMin: "30" }, { mode: "enter", marketIndex: 1, slippage: 0.01 });
    expect(body).toMatchObject({
      entry_type: "chase",
      entry_price: null,
      entry_chase: { low: "99", high: "100.5", offset_bps: "4", clip: "1" },
      expiry_min: 30,
    });
    const whole = plannerBody(
      { ...chase, entryChase: { ...chase.entryChase, clip: "" } },
      { mode: "enter", marketIndex: 1, slippage: 0.01 }
    );
    expect((whole.entry_chase as { clip: unknown }).clip).toBeNull();
  });

  it("says how far a Chase entry has filled, and offers Protect now only while entering", () => {
    const entering = planner({
      qty: "2",
      filled: "0.6",
      params_json: { entry_type: "chase", stop: "95", targets: [] },
      planner: { ...planner().planner!, phase: "entering" },
    });
    expect(plannerPhaseLabel(entering)).toBe("Chasing 0.6 / 2");
    expect(canProtectNow(entering)).toBe(true);
    expect(canProtectNow(planner())).toBe(false);
  });
});

describe("planner Ladder entry", () => {
  const ladder = {
    ...defaultPlannerForm("buy"),
    entryType: "ladder" as const,
    stop: "95",
    entryLadder: { from: "99.5", to: "98", rungs: "4", strength: "even" as const },
  };

  it("needs two prices and 2 to 20 rungs", () => {
    expect(plannerFormBlock({ ...ladder, entryLadder: { ...ladder.entryLadder, to: "" } }, "enter")).toBe(
      "Set the Ladder's from and to"
    );
    expect(plannerFormBlock({ ...ladder, entryLadder: { ...ladder.entryLadder, to: "99.5" } }, "enter")).toBe(
      "The Ladder's from and to must differ"
    );
    for (const rungs of ["1", "21", ""]) {
      expect(plannerFormBlock({ ...ladder, entryLadder: { ...ladder.entryLadder, rungs } }, "enter")).toBe(
        "A Ladder has 2 to 20 rungs"
      );
    }
    expect(plannerFormBlock(ladder, "enter")).toBeNull();
  });

  it("sends its prices, rungs and Strength as the Ladder algo's skew", () => {
    const body = plannerBody(
      { ...ladder, expiryMin: "30", entryLadder: { ...ladder.entryLadder, strength: "low" } },
      { mode: "enter", marketIndex: 1, slippage: 0.01 }
    );
    expect(body).toMatchObject({
      entry_type: "ladder",
      entry_price: null,
      entry_chase: null,
      entry_ladder: { price_from: "99.5", price_to: "98", rungs: 4, strength: "-1" },
      expiry_min: 30,
    });
    expect(plannerBody(ladder, { mode: "attach", marketIndex: 1, slippage: 0.01 }).entry_ladder).toBeNull();
  });

  it("says how far a Ladder entry has filled", () => {
    const entering = planner({
      qty: "2",
      filled: "0.5",
      params_json: { entry_type: "ladder", stop: "95", targets: [] },
      planner: { ...planner().planner!, phase: "entering" },
    });
    expect(plannerPhaseLabel(entering)).toBe("Laddering 0.5 / 2");
    expect(canProtectNow(entering)).toBe(true);
  });
});
