// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useNextHour } from "@/hooks/useNextHour";

describe("useNextHour", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("names the next top of the hour and moves on once it passes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.UTC(2026, 9, 21, 14, 59, 30));
    const { result } = renderHook(() => useNextHour());
    expect(result.current).toBe(Date.UTC(2026, 9, 21, 15, 0, 0));
    act(() => {
      vi.advanceTimersByTime(31_000);
    });
    expect(result.current).toBe(Date.UTC(2026, 9, 21, 16, 0, 0));
  });
});
