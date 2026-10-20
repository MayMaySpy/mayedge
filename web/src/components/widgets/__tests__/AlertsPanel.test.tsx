// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertsPanel } from "@/components/widgets/AlertsPanel";
import { api } from "@/lib/api";
import { notifyErr, notifyOk } from "@/lib/notify";

vi.mock("@/lib/notify", () => ({
  notifyDesk: vi.fn(),
  notifyOk: vi.fn(),
  notifyErr: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function openFilters() {
  await userEvent.click(screen.getByRole("button", { name: "Filters" }));
}

describe("AlertsPanel pushes", () => {
  it("hides the test line when pushes are off", async () => {
    vi.spyOn(api, "alertStats").mockResolvedValue({ hours: 24, rules: [] });
    vi.spyOn(api, "pushStatus").mockResolvedValue({
      enabled: false,
      chat_set: false,
      alerts: "held",
      algos: "lifecycle",
    });
    render(<AlertsPanel />);
    await openFilters();
    expect(screen.queryByText("Pushes: on")).toBeNull();
    expect(screen.queryByRole("button", { name: "Send test" })).toBeNull();
  });

  it("sends a test push when they are on", async () => {
    vi.spyOn(api, "alertStats").mockResolvedValue({ hours: 24, rules: [] });
    vi.spyOn(api, "pushStatus").mockResolvedValue({
      enabled: true,
      chat_set: true,
      alerts: "held",
      algos: "lifecycle",
    });
    vi.spyOn(api, "pushTest").mockResolvedValue({ ok: true });
    render(<AlertsPanel />);
    await openFilters();
    expect(await screen.findByText("Pushes: on")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Send test" }));
    await waitFor(() => expect(api.pushTest).toHaveBeenCalledOnce());
    expect(notifyOk).toHaveBeenCalledWith("Test push sent");
    expect(notifyErr).not.toHaveBeenCalled();
  });
});
