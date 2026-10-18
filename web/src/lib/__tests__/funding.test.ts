import { describe, expect, it } from "vitest";
import {
  averageReading,
  buildFundingBars,
  fundingApr,
  fundingColor,
  headlineAverage,
  isSettled,
} from "@/lib/funding";
import { theme } from "@/lib/theme";

describe("buildFundingBars", () => {
  it("draws APR, coloured by who pays", () => {
    const bars = buildFundingBars(
      [
        { time: 3600, rate: 0.001, settled: true },
        { time: 7200, rate: -0.002, settled: true },
      ],
      3600,
      null,
    );
    expect(bars.map((bar) => ("value" in bar ? bar.value : null))).toEqual([8.76, -17.52]);
    expect(bars.map((bar) => ("color" in bar ? bar.color : null))).toEqual([theme.ask, theme.bid]);
  });

  it("breaks the bars when an hour is missing", () => {
    const bars = buildFundingBars(
      [
        { time: 3600, rate: 0.001, settled: true },
        { time: 14400, rate: 0.001, settled: true },
      ],
      3600,
      null,
    );
    expect(bars.map((bar) => bar.time)).toEqual([3600, 7200, 14400]);
    expect("value" in bars[1]).toBe(false);
  });

  it("puts the live estimate on the open bucket, faint", () => {
    const bars = buildFundingBars([{ time: 3600, rate: 0.001, settled: true }], 3600, {
      time: 7200,
      rate: 0.002,
    });
    expect(bars).toHaveLength(2);
    expect(isSettled(bars[0])).toBe(true);
    expect(isSettled(bars[1])).toBe(false);
    expect("color" in bars[1] ? bars[1].color : null).toBe(fundingColor(fundingApr(0.002), false));
  });

  it("refreshes an estimate bucket and never overwrites a settled one", () => {
    const est = buildFundingBars([{ time: 7200, rate: 0.001, settled: false }], 3600, {
      time: 7200,
      rate: 0.003,
    });
    expect("value" in est[0] ? est[0].value : null).toBeCloseTo(fundingApr(0.003));
    const paid = buildFundingBars([{ time: 7200, rate: 0.001, settled: true }], 3600, {
      time: 7200,
      rate: 0.003,
    });
    expect("value" in paid[0] ? paid[0].value : null).toBeCloseTo(fundingApr(0.001));
    expect(isSettled(paid[0])).toBe(true);
  });
});

describe("headlineAverage", () => {
  const avg = (hours: number, rate: number | null = 0.001) => ({
    windows: [
      { label: "7d", days: 7, hours: Math.min(hours, 168), rate },
      { label: "1y", days: 365, hours, rate },
    ],
    first_time: null,
  });

  it("names the full year once the desk holds it", () => {
    expect(headlineAverage(avg(8700))).toEqual({ label: "1y", apr: fundingApr(0.001) });
  });

  it("names the span it really holds when that is shorter", () => {
    expect(headlineAverage(avg(24 * 12 + 5))?.label).toBe("12d");
    expect(headlineAverage(avg(9))?.label).toBe("9h");
  });

  it("is empty without prints", () => {
    expect(headlineAverage(avg(0, null))).toBeNull();
    expect(headlineAverage(null)).toBeNull();
    expect(averageReading(undefined)).toBeNull();
  });
});
