// @vitest-environment jsdom
import "@/test/dom";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDraftPreview } from "@/hooks/useDraftPreview";
import { api, type PlannerPreview } from "@/lib/api";

const DRAWN: PlannerPreview = {
  plan: {
    side: "buy",
    entry: "100",
    stop: "95",
    r: "5",
    size: "20",
    targets: [],
    runner: "0",
    risk_usd: "100",
    risk_pct: "1",
    breakeven: "100.1",
    stop_pct: "-5",
    warnings: ["rung under the minimum"],
    steps: [],
  },
  refused: null,
  replaces: [],
  equity: "10000",
  mark: "100",
};

function Probe({ body }: { body: Record<string, unknown> | null }) {
  const preview = useDraftPreview(body);
  return <div>{preview?.plan?.size ?? "none"}</div>;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(api, "plannerPreview").mockResolvedValue(DRAWN);
  vi.spyOn(api, "algoStart").mockResolvedValue({ working: [], history: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useDraftPreview", () => {
  it("the Draft preview waits 250ms and does not start", async () => {
    const view = render(<Probe body={{ stop: "95" }} />);
    expect(screen.getByText("none")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(249);
    expect(api.plannerPreview).not.toHaveBeenCalled();

    view.rerender(<Probe body={{ stop: "90" }} />);
    await vi.advanceTimersByTimeAsync(249);
    expect(api.plannerPreview).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.plannerPreview).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.plannerPreview).mock.calls[0]?.[0]).toEqual({ stop: "90" });
    expect(api.algoStart).not.toHaveBeenCalled();
    expect(screen.getByText("20")).toBeTruthy();
  });
});
