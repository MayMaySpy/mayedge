import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { formatClock } from "@/lib/alertFormat";
import { utcClock, utcDateTime } from "@/lib/utcTime";

// 2026-10-20 16:49:57 UTC, in ms. Auckland is 05:49 the next day.
const MS = 1_792_514_997_035;

describe("desk times", () => {
  const zone = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = "Pacific/Auckland";
  });
  afterAll(() => {
    process.env.TZ = zone;
  });

  it("run under a far zone", () => {
    expect(new Date(MS).getHours()).toBe(5);
  });

  it("are UTC whatever the viewer's zone, from ms or seconds", () => {
    expect(utcClock(MS)).toBe("16:49:57");
    expect(utcClock(Math.floor(MS / 1000))).toBe("16:49:57");
    expect(utcClock(MS, false)).toBe("16:49");
    expect(utcDateTime(MS)).toBe("20 Oct, 16:49");
    expect(utcDateTime(Math.floor(MS / 1000))).toBe("20 Oct, 16:49");
    expect(formatClock(MS)).toBe("16:49");
  });

  it("are 24h", () => {
    expect(utcClock(Date.UTC(2026, 9, 20, 0, 5, 1))).toBe("00:05:01");
    expect(utcClock(Date.UTC(2026, 9, 20, 23, 0, 0))).toBe("23:00:00");
  });

  it("show a dash for no time", () => {
    expect(utcClock(0)).toBe("—");
    expect(utcClock(null)).toBe("—");
    expect(utcDateTime(undefined)).toBe("—");
  });
});
