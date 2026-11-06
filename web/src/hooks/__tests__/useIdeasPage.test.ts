// @vitest-environment jsdom
import "@/test/dom";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIdeasPage } from "@/hooks/useIdeasPage";
import { api, ApiError } from "@/lib/api";
import type { Idea, IdeaPatch } from "@/lib/api.gen";
import { notifyErr } from "@/lib/notify";

vi.mock("@/lib/notify", () => ({ notifyErr: vi.fn(), notifyOk: vi.fn() }));
vi.mock("sonner", () => ({ toast: vi.fn() }));

const ZRO: Idea = {
  id: "idea-1",
  symbol: "ZRO",
  side: "long",
  status: "watching",
  conviction: 2,
  horizon: "swing",
  thesis: "Unlock overhang gone after the 20th.",
  invalidation: "",
  trigger: "",
  tags: [],
  catalysts: [],
  entry_low: null,
  entry_high: null,
  stop: null,
  targets: [],
  planner_ids: [],
  outcome: null,
  review: "",
  created_at: 1,
  updated_at: 100,
  closed_at: null,
  plan_entry: null,
  r: null,
  r_multiples: null,
};

let row: Idea = ZRO;

beforeEach(() => {
  row = { ...ZRO };
  window.history.replaceState(null, "", "/ideas?id=idea-1");
  vi.spyOn(api, "ideas").mockImplementation(async () => ({ ideas: [row] }));
  vi.spyOn(api, "idea").mockImplementation(async () => ({ idea: row, log: [] }));
  vi.spyOn(api, "markets").mockResolvedValue([]);
  // The desk's own rule: a patch that saw an older updated_at is refused.
  vi.spyOn(api, "ideaPatch").mockImplementation(async (_id: string, body: IdeaPatch) => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    if (body.seen_updated_at < row.updated_at) throw new ApiError(409, "Changed elsewhere, reloaded");
    const { seen_updated_at: _seen, ...fields } = body;
    row = { ...row, ...fields, updated_at: row.updated_at + 1 } as Idea;
    return { idea: row };
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.mocked(notifyErr).mockClear();
});

describe("useIdeasPage", () => {
  it("sends quick edits one after another, so none refuses the next", async () => {
    const { result } = renderHook(() => useIdeasPage());
    await waitFor(() => expect(result.current.selected?.id).toBe("idea-1"));
    await act(async () => {
      await Promise.all([
        result.current.patch("idea-1", { thesis: "A sharper thesis, typed fast." }),
        result.current.patch("idea-1", { tags: ["unlock"] }),
        result.current.patch("idea-1", { conviction: 3 }),
      ]);
    });
    expect(notifyErr).not.toHaveBeenCalled();
    const sent = vi.mocked(api.ideaPatch).mock.calls.map(([, body]) => body.seen_updated_at);
    expect(sent).toEqual([100, 101, 102]);
    expect(result.current.selected).toMatchObject({
      thesis: "A sharper thesis, typed fast.",
      tags: ["unlock"],
      conviction: 3,
      updated_at: 103,
    });
  });

  it("keeps an edit still in flight on screen when an earlier answer lands", async () => {
    const { result } = renderHook(() => useIdeasPage());
    await waitFor(() => expect(result.current.selected?.id).toBe("idea-1"));
    let second: Promise<unknown> = Promise.resolve();
    await act(async () => {
      const first = result.current.patch("idea-1", { thesis: "First edit lands first." });
      second = result.current.patch("idea-1", { tags: ["ai"] });
      await first;
    });
    expect(result.current.selected?.tags).toEqual(["ai"]);
    await act(async () => {
      await second;
    });
    expect(result.current.selected?.tags).toEqual(["ai"]);
  });

  it("says why a delete failed and keeps the Idea", async () => {
    vi.spyOn(api, "ideaDelete").mockRejectedValue(new ApiError(500, "Desk is busy"));
    const { result } = renderHook(() => useIdeasPage());
    await waitFor(() => expect(result.current.selected?.id).toBe("idea-1"));
    await act(async () => {
      await expect(result.current.remove("idea-1")).rejects.toThrow("Desk is busy");
    });
    expect(notifyErr).toHaveBeenCalledWith("Desk is busy", "Delete failed");
    expect(result.current.selected?.id).toBe("idea-1");
  });
});
