import { describe, expect, it } from "vitest";
import type { Candle } from "@/lib/api";
import { candleTones, tonePaint, type Tone } from "@/lib/mayRekt";

const UP: readonly Tone[] = ["up-strong", "up-weak"];
const DOWN: readonly Tone[] = ["down-strong", "down-weak"];

function series(n: number, at: (i: number) => Pick<Candle, "open" | "high" | "low" | "close">): Candle[] {
  return Array.from({ length: n }, (_, i) =>
    bar({ time: 1_700_000_000 + i * 60, volume: 10, ...at(i) })
  );
}

function bar(partial: Partial<Candle> & { time: number }): Candle {
  return {
    open: 10,
    high: 11,
    low: 9,
    close: 10,
    volume: 1,
    ...partial,
  };
}

describe("candleTones", () => {
  it("leaves a single bar untoned", () => {
    expect(candleTones([bar({ time: 60 })])).toEqual([null]);
  });

  it("ends a non-trending series Neutral", () => {
    const tones = candleTones(series(200, () => ({ open: 100, high: 101, low: 99, close: 100 })));
    expect(tones).toHaveLength(200);
    expect(tones[199]).toBe("neutral");
  });

  it("ends a rising series on an Up tone", () => {
    const tones = candleTones(
      series(200, (i) => {
        const low = 100 + i;
        return { open: low, high: low + 1, low, close: low + 1 };
      })
    );
    const last = tones[199];
    expect(UP).toContain(last);
    expect(last === "neutral" || DOWN.includes(last!) || String(last).startsWith("breakdown")).toBe(
      false
    );
  });

  it("ends a falling series on a Down tone", () => {
    const tones = candleTones(
      series(200, (i) => {
        const high = 400 - i;
        return { open: high, high, low: high - 1, close: high - 1 };
      })
    );
    const last = tones[199];
    expect(DOWN).toContain(last);
    expect(last === "neutral" || UP.includes(last!) || String(last).startsWith("breakout")).toBe(
      false
    );
  });

  it("paints a breakout instead of Up when three closes under the low band are followed by a close through the high band", () => {
    // Flat band: low line on 99, high line on 101, close inside.
    // Then three closes step under that low line, then one close through the high line.
    // Breakout is earlier in the color chain than Up.
    const flat = series(120, () => ({ open: 100, high: 101, low: 99, close: 100 }));
    const start = flat[flat.length - 1].time;
    const dip = [98, 96, 94].map((close, step) =>
      bar({
        time: start + (step + 1) * 60,
        open: close + 2,
        high: close + 2,
        low: close,
        close,
        volume: 10,
      })
    );
    const spike = bar({
      time: start + 4 * 60,
      open: 94,
      high: 110,
      low: 94,
      close: 108,
      volume: 10,
    });
    const tones = candleTones([...flat, ...dip, spike]);
    expect(tones[119]).toBe("neutral");
    expect(["breakout-strong", "breakout-weak"] as const).toContain(tones[tones.length - 1]);
  });
});

describe("tonePaint", () => {
  // Pine color.new(color, 30) is 30% transparent. v6 built-in hex from the color table.
  it("paints strong tones opaque and weak tones at Pine transparency 30", () => {
    const paints: Record<string, { strong: string; weak: string }> = {
      breakout: { strong: "rgb(253, 216, 53)", weak: "rgba(253, 216, 53, 0.7)" },
      breakdown: { strong: "rgb(156, 39, 176)", weak: "rgba(156, 39, 176, 0.7)" },
      uw: { strong: "rgb(76, 175, 80)", weak: "rgba(76, 175, 80, 0.7)" },
      up: { strong: "rgb(0, 230, 118)", weak: "rgba(0, 230, 118, 0.7)" },
      down: { strong: "rgb(242, 54, 69)", weak: "rgba(242, 54, 69, 0.7)" },
    };
    for (const [name, paint] of Object.entries(paints)) {
      const strong = tonePaint(`${name}-strong` as Tone);
      const weak = tonePaint(`${name}-weak` as Tone);
      expect(strong).toEqual({ color: paint.strong, borderColor: paint.strong, wickColor: paint.strong });
      expect(weak).toEqual({ color: paint.weak, borderColor: paint.weak, wickColor: paint.weak });
    }
  });
});
