// @vitest-environment jsdom
import "@/test/dom";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PortfolioToday } from "@/components/widgets/PortfolioToday";
import { api, type PortfolioNow } from "@/lib/api";

const kind = (value: string, change: string) => ({
  value,
  value_at_open: value,
  change,
  change_pct: null,
  flows: "0",
});

const NOW: PortfolioNow = {
  ts: 1,
  open: 0,
  total: { value: "5681.19", value_at_open: "5493.28", change: "187.88", change_pct: "3.42", flows: "0" },
  kinds: {
    perps: kind("1221", "27.94"),
    spot: kind("1218.25", "16.89"),
    llp: kind("0", "0"),
    staking: kind("3241.94", "143.04"),
  },
  mismatch: [],
  spot: [],
  pools: [],
  unlocks: [],
};

function show(enabled = true) {
  return render(
    <TooltipProvider>
      <PortfolioToday enabled={enabled} />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("PortfolioToday", () => {
  it("shows today's change since local midnight from the plain answer", async () => {
    const read = vi.spyOn(api, "portfolio").mockResolvedValue(NOW);
    show();
    expect(await screen.findByText("+187.88")).toBeTruthy();
    expect(screen.getByText("+3.42%")).toBeTruthy();
    const [open, detail] = read.mock.calls[0];
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    expect(open).toBe(midnight.getTime());
    expect(detail).toBe(false);
  });

  it("asks again each minute, and drops a figure older than five minutes", async () => {
    const read = vi.spyOn(api, "portfolio").mockResolvedValueOnce(NOW).mockRejectedValue(new Error("down"));
    show();
    expect(await screen.findByText("+187.88")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(read).toHaveBeenCalledTimes(2);
    expect(screen.getByText("+187.88")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60_000);
    });
    expect(screen.queryByText("+187.88")).toBeNull();
  });

  it("shows nothing and asks nothing when trading is off", () => {
    const read = vi.spyOn(api, "portfolio").mockResolvedValue(NOW);
    const { container } = show(false);
    expect(container.textContent).toBe("");
    expect(read).not.toHaveBeenCalled();
  });

  it("marks a mismatch", async () => {
    vi.spyOn(api, "portfolio").mockResolvedValue({ ...NOW, mismatch: [{ kind: "spot", drift: "4.2" }] });
    show();
    expect(await screen.findByLabelText("Mismatch")).toBeTruthy();
  });
});
