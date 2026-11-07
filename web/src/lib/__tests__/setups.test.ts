import { describe, expect, it } from "vitest";
import { setupArrow, setupName } from "@/lib/setups";

describe("setups", () => {
  it("names each Setup as the rules do, and passes an unknown kind through", () => {
    expect(setupName("oi_price")).toBe("OI without price");
    expect(setupName("flush")).toBe("Liquidation flush");
    expect(setupName("new_kind")).toBe("new_kind");
  });

  it("shows an arrow only for a Setup with a direction", () => {
    expect(setupArrow({ direction: "up" })).toBe("↑");
    expect(setupArrow({ direction: "down" })).toBe("↓");
    expect(setupArrow({ direction: "flat" })).toBe("");
  });
});
