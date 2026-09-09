import { afterEach, describe, expect, it } from "vitest";
import { getLimitPricePick, pickLimitPrice, resetLimitPricePick } from "@/lib/ticketFill";

describe("pickLimitPrice", () => {
  afterEach(() => {
    resetLimitPricePick();
  });

  it("stores the raw book price and bumps seq", () => {
    pickLimitPrice("4123.5");
    const first = getLimitPricePick();
    expect(first?.price).toBe("4123.5");
    pickLimitPrice("4123.5");
    const again = getLimitPricePick();
    expect(again?.price).toBe("4123.5");
    expect(again?.seq).toBe((first?.seq ?? 0) + 1);
  });

  it("ignores blank prices", () => {
    pickLimitPrice("   ");
    expect(getLimitPricePick()).toBeNull();
  });
});
