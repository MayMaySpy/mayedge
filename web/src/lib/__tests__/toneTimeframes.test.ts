import { describe, expect, it } from "vitest";
import {
  DEFAULT_TONE_TIMEFRAMES,
  TONE_TIMEFRAME_CAP,
  toggleToneTimeframe,
} from "@/lib/toneTimeframes";

describe("toggleToneTimeframe", () => {
  it("starts from 30m and 4h", () => {
    expect(DEFAULT_TONE_TIMEFRAMES).toEqual(["30m", "4h"]);
    expect(TONE_TIMEFRAME_CAP).toBe(2);
  });

  it("removes a selected timeframe", () => {
    expect(toggleToneTimeframe(["30m", "4h"], "30m")).toEqual(["4h"]);
  });

  it("adds a timeframe while under the cap", () => {
    expect(toggleToneTimeframe(["4h"], "1h")).toEqual(["4h", "1h"]);
  });

  it("ignores a third timeframe", () => {
    const current = ["30m", "4h"];
    expect(toggleToneTimeframe(current, "1h")).toBe(current);
  });

  it("allows an empty set", () => {
    expect(toggleToneTimeframe(["30m"], "30m")).toEqual([]);
  });
});
