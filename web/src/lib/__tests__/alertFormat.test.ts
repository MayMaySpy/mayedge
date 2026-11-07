import { describe, expect, it } from "vitest";
import type { AlertEvent, AlertFact } from "@/lib/api";
import { eventLine, heldText, shownAlerts, toastCopy } from "@/lib/alertFormat";

const NOW = 1_800_000_000_000;

const MOVE: AlertFact = {
  kind: "move",
  direction: "up",
  value: 1.8,
  unit: "pct",
  window: "5m",
  size: 1.2,
  multiple: 14.4,
  usual: 0.125,
  share: 0.04,
};

function alert(id: string, extra: Partial<AlertEvent> = {}): AlertEvent {
  return {
    id,
    ts: NOW,
    started_at: NOW,
    symbol: "ETH",
    market_index: 1,
    rule: "move",
    severity: 2,
    direction: "up",
    size: 1.25,
    price: 100.5,
    facts: [MOVE],
    held: "",
    note: "",
    ...extra,
  };
}

describe("eventLine", () => {
  it("says when it fired, in UTC", () => {
    expect(eventLine(alert("a")).tooltip).toContain("Fired 08:00:00 UTC");
  });

  it("reads price first: the move, its span and price, then its usual and the tape", () => {
    const line = eventLine(
      alert("a", {
        facts: [
          MOVE,
          { kind: "volume", direction: "flat", value: 480_000, unit: "usd", window: "5m", multiple: 6.2 },
          { kind: "oi", direction: "down", value: -0.9, unit: "pct", window: "5m", usd: -1_200_000 },
          { kind: "day_high", direction: "up", value: 100.5, unit: "px" },
          { kind: "funding", direction: "up", value: 0.012, unit: "pct_hr", z: 5.5 },
        ],
      })
    );
    expect(line.name).toBe("ETH");
    expect(line.label).toBe("+1.80% in 5m · 100.5");
    expect(line.detail).toBe(
      "14× its usual 5m · volume 6.2× ($480k) · OI -0.90% (−$1.2M) · at the day's high · funding +0.0120%/h"
    );
  });

  it("shows a minute too small to print as flat", () => {
    const line = eventLine(
      alert("z", {
        rule: "liqs",
        direction: "down",
        facts: [
          { kind: "liqs", direction: "down", value: 1_200_000, unit: "usd", size: 2.2, bps: 44.4 },
          { kind: "move", direction: "down", value: -0.001, unit: "pct", window: "1m" },
        ],
      })
    );
    expect(line.label).toBe("$1.2M longs liquidated · 100.5");
    expect(line.detail).toBe("44 bps of open interest · 0.00% in 1m");
  });

  it("reads a broken level as the level", () => {
    const line = eventLine(
      alert("w", {
        rule: "week_high",
        facts: [
          { kind: "week_high", direction: "up", value: 110, unit: "px", size: 1 },
          { kind: "move", direction: "up", value: 0.3, unit: "pct", window: "1m" },
        ],
      })
    );
    expect(line.label).toBe("through the week high 110");
    expect(line.detail).toBe("+0.30% in 1m");
  });

  it("says how far past the board a market went", () => {
    const line = eventLine(alert("a", { facts: [{ ...MOVE, value: 2.5, excess: 1.5 }] }));
    expect(line.label).toBe("+2.50% in 5m · 100.5");
    expect(line.detail).toBe("14× its usual 5m · +1.50% past the board");
  });

  it("still reads a spike from before ADR 0027", () => {
    const line = eventLine(
      alert("v", {
        rule: "volume",
        direction: "flat",
        facts: [
          { kind: "volume", direction: "flat", value: 100_000, unit: "usd", window: "1m", size: 1.1, multiple: 3.3 },
        ],
      })
    );
    expect(line.label).toBe("volume $100k in 1m");
    expect(line.detail).toBe("3.3× the hour's biggest minute");

    const board = eventLine(
      alert("b", {
        symbol: "BTC",
        market_index: -1,
        rule: "board",
        direction: "down",
        facts: [
          { kind: "board", direction: "down", value: -0.86, unit: "pct", window: "22/22", size: 1.7, liquid: 43 },
        ],
      })
    );
    expect(board.name).toBe("Market");
    expect(board.label).toBe("board -0.86% in 5m");
    expect(board.detail).toBe("22 of 22 movers down");
  });
});

describe("heldText", () => {
  it("says whether a move runs with the Position or against it", () => {
    expect(heldText(alert("a", { held: "long", direction: "down" }))).toBe("against your long");
    expect(heldText(alert("a", { held: "long", direction: "up" }))).toBe("with your long");
    expect(heldText(alert("a", { held: "short", direction: "up" }))).toBe("against your short");
    expect(heldText(alert("a", { held: "order" }))).toBe("near your order");
    expect(heldText(alert("a"))).toBe("");
  });

  it("does not grade a row that points nowhere", () => {
    expect(heldText(alert("v", { held: "long", rule: "volume", direction: "flat" }))).toBe("your long");
  });

  it("does not grade a row that is about the Position itself", () => {
    const near = alert("a", {
      held: "long",
      rule: "near_liq",
      direction: "down",
      facts: [{ kind: "near_liq", direction: "down", value: 4.2, unit: "pct", size: 2.4 }],
    });
    expect(heldText(near)).toBe("your long");
    expect(eventLine(near).label).toBe("4.2% from liquidation · 100.5");
    expect(eventLine(near).detail).toBe("your long");
  });
});

describe("toastCopy", () => {
  it("leads with the market and the fact", () => {
    expect(toastCopy(alert("a"), "ETH-USD")).toEqual({
      title: "▲ ETH-USD · +1.80% in 5m · 100.5",
      description: "14× its usual 5m",
    });
  });
});

describe("shownAlerts", () => {
  const opts = { minSeverity: 2, favoritesOnly: false, favorites: [], muted: new Set<string>() };

  it("is newest first", () => {
    const rows = shownAlerts(
      [alert("old", { started_at: NOW - 60_000 }), alert("new")],
      opts
    );
    expect(rows.map((r) => r.id)).toEqual(["new", "old"]);
  });

  it("keeps a Held market and the Market row under Favorites only", () => {
    const rows = shownAlerts(
      [
        alert("other", { symbol: "SOL" }),
        alert("fav", { symbol: "ETH" }),
        alert("held", { symbol: "ZEC", held: "short" }),
        alert("board", { symbol: "BTC", market_index: -1, rule: "board" }),
      ],
      { ...opts, favoritesOnly: true, favorites: ["ETH"] }
    );
    expect(rows.map((r) => r.id).sort()).toEqual(["board", "fav", "held"]);
  });

  it("hides a muted market, and never the Market row", () => {
    const rows = shownAlerts(
      [alert("btc", { symbol: "BTC" }), alert("board", { symbol: "BTC", market_index: -1, rule: "board" })],
      { ...opts, muted: new Set(["BTC"]) }
    );
    expect(rows.map((r) => r.id)).toEqual(["board"]);
  });

  it("shows only Urgent when asked", () => {
    const rows = shownAlerts([alert("n"), alert("u", { severity: 3 })], { ...opts, minSeverity: 3 });
    expect(rows.map((r) => r.id)).toEqual(["u"]);
  });
});
