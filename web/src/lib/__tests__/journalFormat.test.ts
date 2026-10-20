import { describe, expect, it } from "vitest";
import { price, rValue, ratio, size, when } from "@/lib/journalFormat";
import { isJournalPath, parsePath } from "@/lib/deskRoute";

describe("journal numbers", () => {
  it("cuts the full-precision strings the summary sends", () => {
    // The values that ran off the Journal tab.
    expect(ratio("1.041666974894288296626184072")).toBe((1.04).toLocaleString(undefined, { minimumFractionDigits: 2 }));
    expect(rValue("-1.229662926377033982289568748")).toBe(`-${(1.23).toLocaleString(undefined, { minimumFractionDigits: 2 })}R`);
    expect(rValue("2")).toBe(`+${(2).toLocaleString(undefined, { minimumFractionDigits: 2 })}R`);
    expect(ratio(null)).toBe("—");
    expect(rValue(null)).toBe("—");
  });

  it("shows a price to about six significant digits", () => {
    expect(price("3.176836908")).toBe((3.17684).toLocaleString(undefined, { minimumFractionDigits: 5 }));
    expect(price("2412.1833")).toBe((2412.18).toLocaleString(undefined, { minimumFractionDigits: 2 }));
    expect(price("0.00423")).toBe((0.00423).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 8 }));
    expect(price("0.0000123456")).toBe((0.0000123456).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 10 }));
    expect(size("0.40000")).toBe((0.4).toLocaleString());
  });
});

describe("journal route", () => {
  it("is its own page and never a symbol", () => {
    expect(isJournalPath("/journal")).toBe(true);
    expect(isJournalPath("/Journal/")).toBe(true);
    expect(isJournalPath("/ETH")).toBe(false);
    expect(parsePath("/journal").symbol).not.toBe("JOURNAL");
  });
});

describe("journal times", () => {
  it("are UTC whatever the viewer's zone", () => {
    // 2026-10-20 16:49:57 UTC, in ms and in seconds.
    expect(when(1_792_514_997_035)).toContain("16:49");
    expect(when(1_792_514_997)).toContain("16:49");
  });
});
