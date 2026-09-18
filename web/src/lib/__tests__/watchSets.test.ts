import { afterEach, describe, expect, it } from "vitest";
import {
  addToWatchSet,
  assignWatchPane,
  createWatchSet,
  deleteWatchSet,
  getWatchDesk,
  parseWatchStorage,
  removeFromWatchSet,
  renameWatchSet,
  resetWatchDesk,
  samplingSymbols,
  setWatchLabels,
  setWatchLayout,
} from "@/lib/watchSets";

describe("parseWatchStorage", () => {
  it("promotes a legacy Watchlist into a Watch Set", () => {
    const desk = parseWatchStorage(null, JSON.stringify(["BTC", "ETH"]));
    expect(desk.sets).toHaveLength(1);
    expect(desk.sets[0].name).toBe("Watch");
    expect(desk.sets[0].symbols).toEqual(["BTC", "ETH"]);
    expect(desk.layout).toBe(1);
    expect(desk.labels).toBe(true);
    expect(desk.panes[0]).toBe(desk.sets[0].id);
    expect(desk.panes.slice(1)).toEqual([null, null, null]);
  });

  it("prefers a Watch desk over a leftover Watchlist", () => {
    const desk = parseWatchStorage(
      JSON.stringify({
        sets: [{ id: "a", name: "Majors", symbols: ["SOL"] }],
        layout: 2,
        panes: ["a", null, null, null],
        labels: false,
      }),
      JSON.stringify(["BTC"])
    );
    expect(desk.sets[0].symbols).toEqual(["SOL"]);
    expect(desk.sets[0].name).toBe("Majors");
    expect(desk.layout).toBe(2);
    expect(desk.labels).toBe(false);
  });

  it("starts with one empty Watch Set", () => {
    const desk = parseWatchStorage(null, null);
    expect(desk.sets).toHaveLength(1);
    expect(desk.sets[0].name).toBe("Watch");
    expect(desk.sets[0].symbols).toEqual([]);
    expect(desk.layout).toBe(1);
    expect(desk.labels).toBe(true);
  });
});

describe("Watch Set", () => {
  afterEach(() => {
    resetWatchDesk();
  });

  it("prepends a Market and ignores duplicates", () => {
    const id = getWatchDesk().sets[0].id;
    addToWatchSet(id, "ETH");
    addToWatchSet(id, "BTC");
    addToWatchSet(id, "ETH");
    expect(getWatchDesk().sets[0].symbols).toEqual(["BTC", "ETH"]);
  });

  it("removes a Market", () => {
    const id = getWatchDesk().sets[0].id;
    addToWatchSet(id, "SOL");
    addToWatchSet(id, "ETH");
    addToWatchSet(id, "BTC");
    removeFromWatchSet(id, "ETH");
    expect(getWatchDesk().sets[0].symbols).toEqual(["BTC", "SOL"]);
  });

  it("drops the last Market when adding past 8 so newest stay", () => {
    const id = getWatchDesk().sets[0].id;
    for (const s of ["A", "B", "C", "D", "E", "F", "G", "H"]) addToWatchSet(id, s);
    addToWatchSet(id, "SOL");
    expect(getWatchDesk().sets[0].symbols).toEqual(["SOL", "H", "G", "F", "E", "D", "C", "B"]);
  });

  it("creates a Watch Set with an id that does not collide with a stored Set", () => {
    resetWatchDesk();
    const existing = getWatchDesk().sets[0].id;
    const created = createWatchSet("AI");
    expect(created).toBeTruthy();
    expect(created).not.toBe(existing);
    expect(getWatchDesk().sets.map((s) => s.id)).toEqual([existing, created]);
  });

  it("creates a Watch Set up to 12 and ignores further creates", () => {
    const ids = [getWatchDesk().sets[0].id];
    for (let i = 0; i < 11; i++) {
      const id = createWatchSet();
      expect(id).toBeTruthy();
      ids.push(id as string);
    }
    expect(createWatchSet()).toBeNull();
    expect(getWatchDesk().sets).toHaveLength(12);
    expect(new Set(ids).size).toBe(12);
  });

  it("renames a Watch Set", () => {
    const id = getWatchDesk().sets[0].id;
    renameWatchSet(id, "  Majors  ");
    expect(getWatchDesk().sets[0].name).toBe("Majors");
    renameWatchSet(id, "   ");
    expect(getWatchDesk().sets[0].name).toBe("Majors");
  });

  it("deleting the last Watch Set clears its Watchlist", () => {
    const id = getWatchDesk().sets[0].id;
    addToWatchSet(id, "BTC");
    deleteWatchSet(id);
    const desk = getWatchDesk();
    expect(desk.sets).toHaveLength(1);
    expect(desk.sets[0].id).toBe(id);
    expect(desk.sets[0].symbols).toEqual([]);
    expect(desk.sets[0].name).toBe("Watch");
  });

  it("deleting a Watch Set frees its panes", () => {
    const a = getWatchDesk().sets[0].id;
    const b = createWatchSet("AI") as string;
    assignWatchPane(1, b);
    setWatchLayout(2);
    deleteWatchSet(b);
    const desk = getWatchDesk();
    expect(desk.sets.map((s) => s.id)).toEqual([a]);
    expect(desk.panes[1]).toBeNull();
  });
});

describe("Watch panes", () => {
  afterEach(() => {
    resetWatchDesk();
  });

  it("assigns a Watch Set to a pane and keeps layout 1, 2, or 4", () => {
    const a = getWatchDesk().sets[0].id;
    const b = createWatchSet("AI") as string;
    assignWatchPane(1, b);
    setWatchLayout(4);
    setWatchLayout(3 as never);
    const desk = getWatchDesk();
    expect(desk.layout).toBe(4);
    expect(desk.panes[0]).toBe(a);
    expect(desk.panes[1]).toBe(b);
  });

  it("toggles Names on the right", () => {
    expect(getWatchDesk().labels).toBe(true);
    setWatchLabels(false);
    expect(getWatchDesk().labels).toBe(false);
  });
});

describe("samplingSymbols", () => {
  it("unions Markets across assigned panes, including hidden ones", () => {
    const desk = parseWatchStorage(
      JSON.stringify({
        sets: [
          { id: "a", name: "Majors", symbols: ["BTC", "ETH"] },
          { id: "b", name: "AI", symbols: ["ETH", "SOL"] },
        ],
        layout: 1,
        panes: ["a", "b", null, null],
        labels: true,
      }),
      null
    );
    expect(samplingSymbols(desk)).toEqual(["BTC", "ETH", "SOL"]);
  });
});
