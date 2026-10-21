import { beforeEach, describe, expect, it } from "vitest";
import { FILLS_KEY, loadFills } from "@/components/widgets/chart/chartPrefs";

describe("loadFills", () => {
  beforeEach(() => localStorage.clear());

  it("shows fills until they are turned off", () => {
    expect(loadFills()).toBe(true);
    localStorage.setItem(FILLS_KEY, "0");
    expect(loadFills()).toBe(false);
    localStorage.setItem(FILLS_KEY, "1");
    expect(loadFills()).toBe(true);
  });
});
