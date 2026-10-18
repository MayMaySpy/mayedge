import { describe, expect, it } from "vitest";
import { algoPluginById } from "@/lib/algoPlugins";

const ladderPlugin = algoPluginById("ladder")!;

describe("ladder ticket", () => {
  it("blocks orders under the quote minimum at the low end of the range", () => {
    // MON at 0.02: the $10 minimum is 500 at the touch, 2000 at 0.005.
    const state = { ...(ladderPlugin.defaultState as Record<string, unknown>), priceFrom: "0.01", priceTo: "0.005", orders: "35", window: "20" };
    const ctx = { sizeNum: 40000, decimals: 1, minSz: 500, symbol: "MON", minBase: 250, minQuote: 10 };
    expect(ladderPlugin.blockReason?.(state, ctx)).toMatch(/^Orders near 0\.005 must be ≥ 2000 \(\$10 minimum\)/);
    expect(ladderPlugin.blockReason?.({ ...state, orders: "10" }, ctx)).toBeNull();
  });
});
