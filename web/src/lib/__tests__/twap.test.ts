import { describe, expect, it } from "vitest";
import {
  TWAP_MAX_SECONDS,
  TWAP_MIN_SECONDS,
  TWAP_SLICE_SECONDS,
  formatTwapRuntime,
  twapDurationSeconds,
  twapFreqLabel,
  twapFreqSeconds,
  twapOrderCount,
  twapSlipFromMaxPrice,
} from "@/lib/algos";

describe("twapDurationSeconds", () => {
  it("combines hours and minutes", () => {
    expect(twapDurationSeconds("1", "30")).toBe(5400);
    expect(twapDurationSeconds("", "30")).toBe(1800);
    expect(twapDurationSeconds("0", "1")).toBe(60);
  });

  it("rejects outside 1m–30d", () => {
    expect(twapDurationSeconds("", "0")).toBeNull();
    expect(twapDurationSeconds("", "0.5")).toBeNull();
    expect(twapDurationSeconds(String(30 * 24), "1")).toBeNull();
    expect(twapDurationSeconds("", String(TWAP_MIN_SECONDS / 60))).toBe(TWAP_MIN_SECONDS);
    expect(twapDurationSeconds(String(TWAP_MAX_SECONDS / 3600), "0")).toBe(TWAP_MAX_SECONDS);
  });
});

describe("twapOrderCount", () => {
  it("matches Lighter: duration/30s + 1", () => {
    expect(TWAP_SLICE_SECONDS).toBe(30);
    expect(twapOrderCount(60)).toBe(3);
    expect(twapOrderCount(900)).toBe(31);
    expect(twapOrderCount(1800)).toBe(61);
  });

  it("uses custom slice frequency for advanced", () => {
    expect(twapOrderCount(1800, 5)).toBe(361);
    expect(twapOrderCount(1800, 30)).toBe(61);
  });
});

describe("formatTwapRuntime", () => {
  it("renders compact duration", () => {
    expect(formatTwapRuntime(60)).toBe("1m");
    expect(formatTwapRuntime(1800)).toBe("30m");
    expect(formatTwapRuntime(5400)).toBe("1h 30m");
    expect(formatTwapRuntime(86400)).toBe("1d");
  });
});

describe("twapSlipFromMaxPrice", () => {
  it("is the absolute distance from mark", () => {
    expect(twapSlipFromMaxPrice(2525, 2500)).toBeCloseTo(0.01);
    expect(twapSlipFromMaxPrice(2475, 2500)).toBeCloseTo(0.01);
  });

  it("ignores empty marks", () => {
    expect(twapSlipFromMaxPrice(100, 0)).toBeNull();
  });
});

describe("twapFreq", () => {
  it("accepts 2s–1h", () => {
    expect(twapFreqSeconds("5")).toBe(5);
    expect(twapFreqSeconds("1")).toBeNull();
    expect(twapFreqSeconds("3601")).toBeNull();
  });

  it("labels jitter when randomize is on", () => {
    expect(twapFreqLabel(5, true)).toBe("5s (±40%)");
    expect(twapFreqLabel(5, false)).toBe("5s");
  });
});
