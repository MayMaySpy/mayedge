import { describe, expect, it } from "vitest";
import {
  DEFAULT_PINS,
  PIN_CAP,
  candleSource,
  historyDepth,
  parseTimeframe,
  readStoredPins,
  readStoredTimeframe,
  showsSeconds,
  supportsOpenInterest,
  timeframeMenu,
  togglePin,
} from "@/lib/timeframe";

describe("parseTimeframe", () => {
  it("accepts a count and a unit, and writes the coarsest even unit", () => {
    expect(parseTimeframe("3m")).toEqual({ label: "3m", seconds: 180 });
    expect(parseTimeframe(" 2H ")).toEqual({ label: "2h", seconds: 7200 });
    expect(parseTimeframe("120s")).toEqual({ label: "2m", seconds: 120 });
    expect(parseTimeframe("24h")).toEqual({ label: "1d", seconds: 86400 });
    expect(parseTimeframe("30d")).toEqual({ label: "30d", seconds: 2_592_000 });
    expect(parseTimeframe("90s")).toEqual({ label: "90s", seconds: 90 });
  });

  it("rejects a bare number, a fraction, zero, and anything past 30d", () => {
    expect(parseTimeframe("3")).toBeNull();
    expect(parseTimeframe("1.5h")).toBeNull();
    expect(parseTimeframe("0m")).toBeNull();
    expect(parseTimeframe("31d")).toBeNull();
    expect(parseTimeframe("2w")).toBeNull();
  });
});

describe("candleSource", () => {
  it("fetches the coarsest native resolution that divides the bar", () => {
    expect(candleSource(parseTimeframe("2h")!)).toBe("1h");
    expect(candleSource(parseTimeframe("10m")!)).toBe("5m");
    expect(candleSource(parseTimeframe("3m")!)).toBe("1m");
    expect(candleSource(parseTimeframe("8h")!)).toBe("4h");
    expect(candleSource(parseTimeframe("6h")!)).toBe("1h");
    expect(candleSource(parseTimeframe("12h")!)).toBe("12h");
    expect(candleSource(parseTimeframe("2d")!)).toBe("1d");
  });

  it("uses the 1s buffer when no native bar divides the size", () => {
    expect(candleSource(parseTimeframe("30s")!)).toBe("1s");
    expect(candleSource(parseTimeframe("90s")!)).toBe("1s");
    expect(candleSource(parseTimeframe("1s")!)).toBe("1s");
  });
});

describe("historyDepth", () => {
  it("names the window a folded bar can actually fill", () => {
    expect(historyDepth(parseTimeframe("3m")!)).toBe("~8h");
    expect(historyDepth(parseTimeframe("5s")!)).toBe("~1h");
    expect(historyDepth(parseTimeframe("2h")!)).toBe("~21d");
    expect(historyDepth(parseTimeframe("1m")!)).toBeNull();
    expect(historyDepth(parseTimeframe("1s")!)).toBeNull();
  });
});

describe("supportsOpenInterest", () => {
  it("follows only the stored resolutions", () => {
    expect(supportsOpenInterest(parseTimeframe("15m")!)).toBe(true);
    expect(supportsOpenInterest(parseTimeframe("4h")!)).toBe(true);
    expect(supportsOpenInterest(parseTimeframe("3m")!)).toBe(false);
    expect(supportsOpenInterest(parseTimeframe("1s")!)).toBe(false);
    expect(supportsOpenInterest(parseTimeframe("30m")!)).toBe(false);
    expect(supportsOpenInterest(parseTimeframe("12h")!)).toBe(false);
  });
});

describe("showsSeconds", () => {
  it("is on when the bar is not a whole number of minutes", () => {
    expect(showsSeconds(parseTimeframe("1s")!)).toBe(true);
    expect(showsSeconds(parseTimeframe("90s")!)).toBe(true);
    expect(showsSeconds(parseTimeframe("1m")!)).toBe(false);
  });
});

describe("togglePin", () => {
  it("pins and unpins", () => {
    expect(togglePin(["1m"], "3m")).toEqual({ pins: ["1m", "3m"], full: false });
    expect(togglePin(["1m", "3m"], "3m")).toEqual({ pins: ["1m"], full: false });
  });

  it("refuses an eighth pin", () => {
    const pins = ["1s", "1m", "5m", "15m", "1h", "4h", "1d"];
    expect(pins).toHaveLength(PIN_CAP);
    expect(togglePin(pins, "3m")).toEqual({ pins, full: true });
  });
});

describe("readStoredTimeframe", () => {
  it("keeps a typed size and falls back to 1m", () => {
    expect(readStoredTimeframe("3m")).toBe("3m");
    expect(readStoredTimeframe("60m")).toBe("1h");
    expect(readStoredTimeframe("nope")).toBe("1m");
    expect(readStoredTimeframe(null)).toBe("1m");
  });
});

describe("readStoredPins", () => {
  it("defaults when nothing is stored, and drops junk", () => {
    expect(readStoredPins(null)).toEqual([...DEFAULT_PINS]);
    expect(readStoredPins('["3m","nope","3m","2h"]')).toEqual(["3m", "2h"]);
    expect(readStoredPins("[]")).toEqual([]);
    expect(readStoredPins("not-json")).toEqual([...DEFAULT_PINS]);
  });

  it("keeps the first seven", () => {
    const raw = JSON.stringify(["1s", "1m", "5m", "15m", "1h", "4h", "1d", "3m"]);
    expect(readStoredPins(raw)).toEqual(["1s", "1m", "5m", "15m", "1h", "4h", "1d"]);
  });
});

describe("timeframeMenu", () => {
  it("lists exchange sizes that are not pinned, and the active typed size", () => {
    const groups = timeframeMenu(DEFAULT_PINS, "7m");
    const labels = groups.flatMap((group) => group.rows.map((row) => row.label));
    expect(labels).toContain("30m");
    expect(labels).toContain("12h");
    expect(labels).toContain("7m");
    expect(labels.filter((label) => label === "1m")).toHaveLength(1);
    const minutes = groups.find((group) => group.unit === "Minutes")!;
    expect(minutes.rows.map((row) => row.label)).toEqual([
      "1m",
      "3m",
      "5m",
      "7m",
      "10m",
      "15m",
      "30m",
    ]);
    expect(minutes.rows.find((row) => row.label === "3m")?.depth).toBe("~8h");
    expect(minutes.rows.find((row) => row.label === "1m")?.pinned).toBe(true);
    expect(minutes.rows.find((row) => row.label === "30m")?.pinned).toBe(false);
  });
});
