import { describe, expect, it } from "vitest";
import type { IdeaAlert } from "@/lib/api.gen";
import { alertDistancePct, alertWhat, alertsPaused, armedCount, hasPlanPrice } from "@/lib/ideaAlerts";

function alert(over: Partial<IdeaAlert> = {}): IdeaAlert {
  return {
    id: 1,
    idea_id: "idea-1",
    kind: "level",
    direction: "above",
    price: "2.20",
    pct: null,
    base: null,
    repeat: false,
    label: "",
    note: "",
    status: "armed",
    fires: 0,
    created_at: 1,
    armed_at: 1,
    fired_at: null,
    fired_last: null,
    ...over,
  };
}

describe("price alerts", () => {
  it("says what each kind waits for", () => {
    expect(alertWhat(alert())).toBe("Above 2.20");
    expect(alertWhat(alert({ direction: "below", price: "2.08" }))).toBe("Below 2.08");
    expect(alertWhat(alert({ kind: "move", direction: "either", price: null, pct: "5", base: "2.15" }))).toBe(
      "Moves ±5% from 2.15",
    );
    expect(alertWhat(alert({ kind: "day", direction: "down", price: null, pct: "10" }))).toBe("Daily Change −10%");
  });

  it("measures an armed level from Last", () => {
    expect(alertDistancePct(alert(), 2)).toBeCloseTo(10);
    expect(alertDistancePct(alert({ status: "fired" }), 2)).toBeNull();
    expect(alertDistancePct(alert(), null)).toBeNull();
    expect(alertDistancePct(alert({ kind: "move", price: null, pct: "5" }), 2)).toBeNull();
  });

  it("counts armed alerts, needs a plan price, and waits on an ended Idea", () => {
    expect(armedCount([alert(), alert({ id: 2, status: "fired" })])).toBe(1);
    expect(hasPlanPrice({ entry_low: null, entry_high: null, stop: null, targets: [] })).toBe(false);
    expect(hasPlanPrice({ entry_low: null, entry_high: null, stop: "2", targets: [] })).toBe(true);
    expect(alertsPaused({ status: "dropped" })).toBe(true);
    expect(alertsPaused({ status: "active" })).toBe(false);
  });
});
