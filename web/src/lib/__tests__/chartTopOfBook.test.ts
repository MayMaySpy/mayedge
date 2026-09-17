import { describe, expect, it } from "vitest";
import { stackSizeLabels } from "@/lib/chartTopOfBook";

describe("stackSizeLabels", () => {
  it("leaves y unchanged when the gap is already large enough", () => {
    expect(stackSizeLabels(100, 20, 12)).toEqual({ bidY: 100, askY: 20 });
  });

  it("separates overlapping labels by minGap with bid below ask", () => {
    expect(stackSizeLabels(50, 48, 12)).toEqual({ bidY: 55, askY: 43 });
  });

  it("splits a shared pixel so bid sits below ask", () => {
    expect(stackSizeLabels(50, 50, 12)).toEqual({ bidY: 56, askY: 44 });
  });
});
