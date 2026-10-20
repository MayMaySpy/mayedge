// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertRecordDialog } from "@/components/widgets/AlertRecordDialog";
import { api, type AlertRuleStats } from "@/lib/api";

vi.mock("@/lib/notify", () => ({
  notifyDesk: vi.fn(),
  notifyErr: vi.fn(),
  notifyOk: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const move: AlertRuleStats = {
  rule: "move",
  key: "move",
  n: 24,
  measured: 24,
  left: 1.2,
  against: 0.4,
  left_beats: 0.7,
  opened: 3,
};

describe("AlertRecordDialog", () => {
  it("renders the fixture and updates the what-if when the knob changes", async () => {
    vi.spyOn(api, "alertStats").mockResolvedValue({
      hours: 720,
      by: "rule",
      rules: [move, { ...move, rule: "volume", key: "volume", n: 4, left: null, against: null, left_beats: null }],
    });
    vi.spyOn(api, "alertSettings").mockResolvedValue({
      knobs: { "spike.price_x": 2 },
      by_rule: { move: ["spike.price_x"] },
    });
    const whatIf = vi.spyOn(api, "alertWhatIf").mockImplementation(async (opts) => ({
      rule: opts.rule,
      knob: opts.knob,
      value: opts.value,
      days: opts.days,
      current: 2,
      looser: opts.value < 2,
      baseline: move,
      whatif: { ...move, n: opts.value >= 2 ? 9 : 24, left: 1.5 },
      yaml: `spike:\n  price_x: ${opts.value}`,
    }));

    render(<AlertRecordDialog open onOpenChange={() => {}} />);

    expect((await screen.findAllByText("Price spike")).length).toBeGreaterThan(0);
    expect(screen.getByText(/too few rows/)).toBeTruthy();
    expect(await screen.findByText(/price_x: 2/)).toBeTruthy();

    const input = screen.getByLabelText("Knob value");
    await userEvent.clear(input);
    await userEvent.type(input, "3");
    await waitFor(() => expect(whatIf.mock.calls.some((call) => call[0].value === 3)).toBe(true));
    expect(await screen.findByText(/price_x: 3/)).toBeTruthy();
    expect(screen.getByText("Only tighter values can be tested.")).toBeTruthy();
  });
});
