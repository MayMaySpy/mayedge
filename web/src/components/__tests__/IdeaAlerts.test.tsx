// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IdeaAlerts } from "@/components/ideas/IdeaAlerts";
import { api } from "@/lib/api";
import type { Idea, IdeaAlert } from "@/lib/api.gen";

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
  entry_low: "2.18",
  entry_high: "2.20",
  stop: "2.08",
  targets: [{ price: "2.40", pct: null }],
  planner_ids: [],
  outcome: null,
  review: "",
  created_at: 1,
  updated_at: 2,
  closed_at: null,
  plan_entry: "2.19",
  r: "0.11",
  r_multiples: ["1.91"],
};

const FIRED: IdeaAlert = {
  id: 7,
  idea_id: "idea-1",
  kind: "level",
  direction: "above",
  price: "2.40",
  pct: null,
  base: null,
  repeat: false,
  label: "T1",
  note: "take some",
  status: "fired",
  fires: 1,
  created_at: 1,
  armed_at: 1,
  fired_at: Date.UTC(2026, 9, 22, 14, 5),
  fired_last: "2.4012",
};

beforeEach(() => {
  vi.spyOn(api, "pushStatus").mockResolvedValue({ enabled: false, chat_set: false, alerts: "held", algos: "lifecycle" });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("IdeaAlerts", () => {
  it("says Telegram is off and lists a fired alert", async () => {
    render(<IdeaAlerts idea={ZRO} last={2.3} alerts={[FIRED]} onChanged={async () => {}} />);
    expect(await screen.findByText(/Telegram is off/)).toBeTruthy();
    expect(screen.getByText("Above 2.40")).toBeTruthy();
    expect(screen.getByText("Fired")).toBeTruthy();
    expect(screen.getByText(/14:05 UTC at 2.4012/)).toBeTruthy();
    expect(screen.getByText("take some")).toBeTruthy();
  });

  it("adds a level alert from the price typed", async () => {
    const create = vi.spyOn(api, "ideaAlertCreate").mockResolvedValue({ alert: FIRED });
    const changed = vi.fn(async () => {});
    render(<IdeaAlerts idea={ZRO} last={2.3} alerts={[]} onChanged={changed} />);
    await userEvent.type(screen.getByLabelText("Alert price"), "2.50");
    await userEvent.type(screen.getByLabelText("Alert note"), "breakout");
    await userEvent.click(screen.getByRole("button", { name: /Add alert/ }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith("idea-1", {
      kind: "level",
      direction: null,
      repeat: false,
      note: "breakout",
      price: "2.50",
    });
  });

  it("shows the desk's refusal", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "ideaAlertCreate").mockRejectedValue(new ApiError(422, "Last is already there.", "price"));
    render(<IdeaAlerts idea={ZRO} last={2.3} alerts={[]} onChanged={async () => {}} />);
    await userEvent.type(screen.getByLabelText("Alert price"), "2.3");
    await userEvent.click(screen.getByRole("button", { name: /Add alert/ }));
    expect(await screen.findByText("Last is already there.")).toBeTruthy();
  });

  it("alerts on the plan", async () => {
    const plan = vi.spyOn(api, "ideaAlertsFromPlan").mockResolvedValue({ alerts: [FIRED] });
    render(<IdeaAlerts idea={ZRO} last={2.3} alerts={[]} onChanged={async () => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Alert on my plan" }));
    await waitFor(() => expect(plan).toHaveBeenCalledWith("idea-1"));
  });
});
