import { describe, expect, it } from "vitest";
import { bucketOpen, buildOiLine } from "@/lib/openInterest";

describe("buildOiLine", () => {
  it("breaks the line when a minute is missing", () => {
    const line = buildOiLine(
      [
        { time: 60, open_interest: 10 },
        { time: 240, open_interest: 12 },
      ],
      60,
      null,
    );
    expect(line).toEqual([{ time: 60, value: 10 }, { time: 120 }, { time: 240, value: 12 }]);
  });

  it("updates the open bucket from the live print and leaves earlier gaps", () => {
    const line = buildOiLine([{ time: 60, open_interest: 10 }], 60, { time: 180, value: 14 });
    expect(line).toEqual([{ time: 60, value: 10 }, { time: 120 }, { time: 180, value: 14 }]);
  });

  it("replaces the open bucket when the live print is for that bucket", () => {
    const line = buildOiLine([{ time: 120, open_interest: 10 }], 60, { time: 120, value: 11 });
    expect(line).toEqual([{ time: 120, value: 11 }]);
  });

  it("ignores a live print older than the last sample", () => {
    const line = buildOiLine([{ time: 180, open_interest: 10 }], 60, { time: 60, value: 99 });
    expect(line).toEqual([{ time: 180, value: 10 }]);
  });
});

describe("bucketOpen", () => {
  it("aligns the live print to the chart bar", () => {
    expect(bucketOpen(301, 60)).toBe(300);
    expect(bucketOpen(1_000, 300)).toBe(900);
  });
});
