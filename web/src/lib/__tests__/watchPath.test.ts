import { describe, expect, it } from "vitest";
import { pathFromSamples } from "@/lib/watchPath";

describe("pathFromSamples", () => {
  it("rebases to percent from the first Last in the window", () => {
    expect(
      pathFromSamples(
        [
          { t: 10, px: 100 },
          { t: 11, px: 101 },
        ],
        10
      )
    ).toEqual([
      { t: 10, pct: 0 },
      { t: 11, pct: 1 },
    ]);
  });

  it("ignores samples before the window start", () => {
    expect(
      pathFromSamples(
        [
          { t: 5, px: 50 },
          { t: 10, px: 100 },
          { t: 11, px: 110 },
        ],
        10
      )
    ).toEqual([
      { t: 10, pct: 0 },
      { t: 11, pct: 10 },
    ]);
  });

  it("is empty when no valid Last exists at or after t0", () => {
    expect(pathFromSamples([{ t: 1, px: 100 }], 10)).toEqual([]);
    expect(pathFromSamples([{ t: 10, px: 0 }], 10)).toEqual([]);
    expect(pathFromSamples([], 10)).toEqual([]);
  });

  it("starts a later join at 0% from its first sample after t0", () => {
    expect(
      pathFromSamples(
        [
          { t: 20, px: 200 },
          { t: 21, px: 202 },
        ],
        10
      )
    ).toEqual([
      { t: 20, pct: 0 },
      { t: 21, pct: 1 },
    ]);
  });
});
