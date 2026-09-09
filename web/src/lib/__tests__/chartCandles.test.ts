import { describe, expect, it } from "vitest";
import { foldMinute, formatBarVolume, toSeriesData } from "@/lib/chartCandles";
import type { Candle } from "@/lib/api";

function c(partial: Partial<Candle> & { time: number }): Candle {
  return {
    open: 10,
    high: 11,
    low: 9,
    close: 10.5,
    volume: 1,
    ...partial,
  };
}

describe("toSeriesData", () => {
  it("aligns volume bars with candles and colors down bars", () => {
    const { candles, volume } = toSeriesData([
      c({ time: 100, open: 10, close: 11, volume: 4 }),
      c({ time: 160, open: 11, close: 10, volume: 8 }),
    ]);
    expect(candles.map((b) => b.time)).toEqual([100, 160]);
    expect(volume.map((b) => b.value)).toEqual([4, 8]);
    expect(volume[0].color).toContain("46, 204, 113");
    expect(volume[1].color).toContain("255, 77, 94");
  });

  it("replaces duplicate timestamps instead of freezing the chart", () => {
    const { candles, volume } = toSeriesData([
      c({ time: 100, volume: 1, close: 10 }),
      c({ time: 100, volume: 3, close: 12 }),
    ]);
    expect(candles).toHaveLength(1);
    expect(volume[0].value).toBe(3);
    expect(candles[0].close).toBe(12);
  });
});

describe("foldMinute", () => {
  it("sums volume into the open higher-tf bucket", () => {
    const first = foldMinute([], c({ time: 300, volume: 2, high: 11, low: 9, close: 10 }), 300);
    const next = foldMinute(first, c({ time: 360, volume: 5, high: 12, low: 8, close: 9 }), 300);
    expect(next).toHaveLength(1);
    expect(next[0].time).toBe(300);
    expect(next[0].volume).toBe(7);
    expect(next[0].high).toBe(12);
    expect(next[0].close).toBe(9);
  });
});

describe("formatBarVolume", () => {
  it("compacts large sizes without a dollar sign", () => {
    expect(formatBarVolume(12500)).toBe("12.5k");
    expect(formatBarVolume(0)).toBe("—");
  });
});
