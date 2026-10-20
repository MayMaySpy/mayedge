import { beforeEach, describe, expect, it } from "vitest";
import {
  applyDraftClick,
  chartDraftFor,
  clearChartDraft,
  clickChartDraft,
  draftDistancePct,
  draftOpenMode,
  draftOverlays,
  draftRAt,
  draftSide,
  draftToForm,
  emptyChartDraft,
  moveChartDraft,
  moveDraftLine,
} from "@/lib/chartDraft";
import { theme } from "@/lib/theme";

function drafted(entry: number, stop: number) {
  return applyDraftClick(applyDraftClick(emptyChartDraft(), entry, null), stop, null);
}

beforeEach(() => {
  clearChartDraft("ETH");
  clearChartDraft("BTC");
});

describe("chart draft", () => {
  it("click order picks the side", () => {
    const long = drafted(100, 95);
    expect(long.entry).toBe(100);
    expect(long.stop).toBe(95);
    expect(draftSide(long.entry!, long.stop!)).toBe("buy");

    const short = drafted(100, 110);
    expect(draftSide(short.entry!, short.stop!)).toBe("sell");

    const stuck = applyDraftClick(long, 80, null);
    expect(stuck).toBe(long);
  });

  it("a Position's Draft is a stop", () => {
    const draft = applyDraftClick(emptyChartDraft(), 90, 100);
    expect(draft.entry).toBe(100);
    expect(draft.stop).toBe(90);
    expect(draftSide(draft.entry!, draft.stop!)).toBe("buy");
    const lines = draftOverlays({ draft, decimals: 2, positionEntry: 100 });
    expect(lines.map((l) => l.id)).not.toContain("draft-entry");
    expect(lines[0]?.id).toBe("draft-stop");
  });

  it("opens as Attach when a Position is open", () => {
    expect(draftOpenMode(false)).toBe("enter");
    expect(draftOpenMode(true)).toBe("attach");
    const form = draftToForm(drafted(100, 95), 2, 100);
    expect(form).toMatchObject({ side: "buy", stop: "95.00" });
    expect(form).not.toHaveProperty("entryPrice");
  });

  it("drag snaps a Draft line to the tick", () => {
    clickChartDraft("ETH", 100, null);
    clickChartDraft("ETH", 95, null);
    moveChartDraft("ETH", "draft-entry", "101.23", null);
    expect(chartDraftFor("ETH").entry).toBe(101.23);
    moveChartDraft("ETH", "draft-stop", "94.5", null);
    expect(chartDraftFor("ETH").stop).toBe(94.5);
  });

  it("a dragged target changes its R", () => {
    const draft = drafted(100, 95);
    expect(draftRAt(100, 95, 110)).toBe("2");
    const moved = moveDraftLine(draft, "draft-t0", 112.5, null);
    expect(moved.targets[0]?.r).toBe("2.5");
    expect(moved.targets[1]?.r).toBe("3");
    expect(moveDraftLine(draft, "draft-t0", 90, null)).toBe(draft);
    const entryMoved = moveDraftLine(draft, "draft-entry", 90, null);
    expect(entryMoved.entry).toBe(90);
    expect(entryMoved.targets[0]?.r).toBe(draft.targets[0]?.r);
    expect(moveDraftLine(draft, "draft-entry", 90, 100)).toBe(draft);
  });

  it("labels show price, distance, R and size", () => {
    const lines = draftOverlays({
      draft: drafted(100, 95),
      decimals: 2,
      positionEntry: null,
      size: "20",
      targetQty: ["10", "10"],
    });
    expect(lines.map((l) => l.label)).toEqual([
      "ENTRY 100.00 20",
      "STOP 95.00 5.00%",
      "2R 110.00 10.00% 10",
      "3R 115.00 15.00% 10",
    ]);
    expect(lines[0]?.color).toBe(theme.bid);
    expect(lines[1]?.color).toBe(theme.ask);
    expect(draftDistancePct(100, 95)).toBe("5.00%");
  });

  it("keeps each Market's Draft in memory", () => {
    clickChartDraft("ETH", 100, null);
    clickChartDraft("BTC", 50, null);
    expect(chartDraftFor("ETH").entry).toBe(100);
    expect(chartDraftFor("BTC").entry).toBe(50);
    clearChartDraft("ETH");
    expect(chartDraftFor("ETH").entry).toBeNull();
    expect(chartDraftFor("BTC").entry).toBe(50);
  });

  it("fills the dialog from the same prices", () => {
    expect(draftToForm(drafted(100, 95), 2, null)).toMatchObject({
      side: "buy",
      entryType: "limit",
      entryPrice: "100.00",
      stop: "95.00",
      targets: [
        { kind: "r", value: "2", pct: "50", order: "limit" },
        { kind: "r", value: "3", pct: "50", order: "limit" },
      ],
    });
  });
});
