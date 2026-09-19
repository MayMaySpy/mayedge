import { describe, expect, it } from "vitest";
import { scrollTopForRow } from "@/lib/scanScroll";

describe("scrollTopForRow", () => {
  it("places a row nine ticks down just below a 32px sticky header", () => {
    expect(
      scrollTopForRow({
        scrollTop: 0,
        containerTop: 80,
        rowTop: 80 + 32 + 9 * 36,
        stickyPx: 32,
      })
    ).toBe(324);
  });

  it("does not jump when the row is already under the header", () => {
    expect(
      scrollTopForRow({
        scrollTop: 324,
        containerTop: 80,
        rowTop: 112,
        stickyPx: 32,
      })
    ).toBe(324);
  });
});
