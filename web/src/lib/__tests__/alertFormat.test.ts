import { describe, expect, it } from "vitest";
import type { AlertEvent } from "@/lib/api";
import {
  boardLine,
  eventLine,
  factorSummary,
  recentEvents,
  setupShort,
  toastCopy,
} from "@/lib/alertFormat";

const NOW = 1_800_000_000_000;

function signal(id: string, market: number, startedAgoMs: number, extra: Partial<AlertEvent> = {}): AlertEvent {
  return {
    id,
    ts: NOW - startedAgoMs,
    started_at: NOW - startedAgoMs,
    symbol: `M${market}`,
    market_index: market,
    kind: "signal",
    severity: 2,
    direction: "down",
    value: 5,
    baseline: null,
    unit: "score",
    note: "",
    score: 5,
    setup: "long_flush",
    factors: [
      { kind: "price", value: -1.6, unit: "pct", score: 5.3, window: "1m" },
      { kind: "volume", value: 6.8, unit: "x", score: 5.5, window: "1m" },
      { kind: "liq_cluster", value: 1_200_000, unit: "usd", score: 4.2 },
      { kind: "oi", value: -2, unit: "pct", score: 4.0 },
    ],
    ...extra,
  };
}

describe("alertFormat", () => {
  it("summarises the top three factors in trader units", () => {
    expect(factorSummary(signal("a", 1, 0).factors)).toBe("Px -1.60% · Vol 6.8× · Liqs $1.2M");
  });

  it("falls back for unknown setups", () => {
    expect(setupShort("long_flush")).toBe("Long flush");
    expect(setupShort(undefined)).toBe("Signal");
  });

  it("puts sigma detail in the tooltip, not the row", () => {
    const line = eventLine(signal("a", 1, 0));
    expect(line.detail).not.toContain("σ");
    expect(line.tooltip).toContain("Px -1.60% (1m) · 5.3σ");
  });

  it("hides only the newest episode of a market that is live", () => {
    const rows = recentEvents(
      [signal("new", 1, 30_000), signal("old", 1, 3_600_000), signal("other", 2, 60_000)],
      new Set([1]),
      NOW
    );
    expect(rows.map((r) => r.id)).toEqual(["other", "old"]);
  });

  it("orders recent by start, so updates do not reshuffle the feed", () => {
    const updated = signal("a", 1, 120_000, { ts: NOW });
    const rows = recentEvents([updated, signal("b", 2, 60_000)], new Set(), NOW);
    expect(rows.map((r) => r.id)).toEqual(["b", "a"]);
  });

  it("shows the 5m move on a live row when price is not a factor", () => {
    const row = {
      market_index: 1,
      symbol: "PUMP",
      score: 10.1,
      severity: 3,
      setup: "vol_surge",
      direction: "up",
      factors: [{ kind: "volume" as const, value: 33.5, unit: "x", score: 10.1, window: "1m" }],
      move_pct: 0.42,
      ts: NOW,
    };
    expect(boardLine(row).detail).toBe("Vol 33.5× · 5m +0.42%");
    const withPrice = { ...row, factors: [...row.factors, signal("a", 1, 0).factors![0]] };
    expect(boardLine(withPrice).detail).toBe("Vol 33.5× · Px -1.60%");
  });

  it("shows the excess next to the raw move", () => {
    expect(factorSummary([{ kind: "price", value: 2, unit: "pct", excess: 3.9 }])).toBe(
      "Px +2.00% · ex +3.90%"
    );
  });

  it("names a broad move Market", () => {
    const line = eventLine(
      signal("b", -1, 0, {
        symbol: "BTC",
        setup: "broad_down",
        direction: "down",
        factors: [
          { kind: "broad", value: -1.8, unit: "pct", direction: "down", window: "41/58" },
        ],
      })
    );
    expect(line.name).toBe("Market");
    expect(line.mutable).toBe(false);
    expect(line.label).toBe("Broad down");
    expect(line.detail).toBe("Board -1.8% · 41/58 down");
  });

  it("names holds up and lags", () => {
    expect(setupShort("holds_up")).toBe("Holds up");
    expect(setupShort("lags")).toBe("Lags");
  });

  it("writes a short toast", () => {
    expect(toastCopy(signal("a", 1, 0), "ETH")).toEqual({
      title: "▼ ETH · Long flush",
      description: "Px -1.60% · Vol 6.8× · Liqs $1.2M",
    });
  });
});
