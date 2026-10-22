// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NewIdeaDialog } from "@/components/ideas/NewIdeaDialog";
import { ApiError, type Market } from "@/lib/api";
import type { IdeaBody } from "@/lib/api.gen";

function market(symbol: string, isPerp = true): Market {
  return { market_index: symbol.length, symbol, price_decimals: 2, size_decimals: 1, is_perp: isPerp };
}

const MARKETS = [market("ZRO"), market("HYPE"), market("rhQQQ/USDC", false)];

function createButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /^(Create|Creating…)$/ }) as HTMLButtonElement;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("NewIdeaDialog", () => {
  it("takes a typed symbol in any case and says what is missing", async () => {
    const onCreate = vi.fn(async (_body: IdeaBody) => ({}));
    render(<NewIdeaDialog open markets={MARKETS} seed={null} onOpenChange={() => {}} onCreate={onCreate} />);
    expect(screen.getByText("Pick a market.")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Market"), "zro");
    expect(screen.getByText("Why needs at least 10 characters (0 so far).")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Why"), "Unlock overhang gone after the 20th.");
    expect(createButton().disabled).toBe(false);
    await userEvent.click(createButton());
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    expect(onCreate.mock.calls[0][0]).toMatchObject({ symbol: "ZRO", side: "long" });
  });

  it("names a symbol that is not a listed perp, spot included", async () => {
    render(<NewIdeaDialog open markets={MARKETS} seed={null} onOpenChange={() => {}} onCreate={async () => ({})} />);
    await userEvent.type(screen.getByLabelText("Market"), "abc");
    expect(screen.getByText("ABC is not a listed perp.")).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    expect(createButton().disabled).toBe(true);
    cleanup();
    render(<NewIdeaDialog open markets={MARKETS} seed={null} onOpenChange={() => {}} onCreate={async () => ({})} />);
    await userEvent.type(screen.getByLabelText("Market"), "rhqqq");
    expect(screen.getByText("RHQQQ is not a listed perp.")).toBeTruthy();
  });

  it("colours the side picked: Long green, Short red", async () => {
    render(<NewIdeaDialog open markets={MARKETS} seed={null} onOpenChange={() => {}} onCreate={async () => ({})} />);
    const long = screen.getByRole("button", { name: "Long" });
    const short = screen.getByRole("button", { name: "Short" });
    expect(long.getAttribute("aria-pressed")).toBe("true");
    expect(long.className).toContain("bg-bid");
    await userEvent.click(short);
    expect(short.getAttribute("aria-pressed")).toBe("true");
    expect(short.className).toContain("bg-ask");
    expect(long.className).not.toContain("bg-bid");
  });

  it("creates again after a create, from a clean form", async () => {
    const onCreate = vi.fn(async (_body: IdeaBody) => ({}));
    const view = (open: boolean) => (
      <NewIdeaDialog open={open} markets={MARKETS} seed={null} onOpenChange={() => {}} onCreate={onCreate} />
    );
    const { rerender } = render(view(true));
    await userEvent.type(screen.getByLabelText("Market"), "ZRO");
    await userEvent.type(screen.getByLabelText("Why"), "Unlock overhang gone after the 20th.");
    await userEvent.click(createButton());
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    rerender(view(false));
    rerender(view(true));
    expect((screen.getByLabelText("Why") as HTMLTextAreaElement).value).toBe("");
    await userEvent.type(screen.getByLabelText("Market"), "HYPE");
    await userEvent.type(screen.getByLabelText("Why"), "A slower bid under the listing.");
    expect(createButton().disabled).toBe(false);
    await userEvent.click(createButton());
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(2));
    expect(onCreate.mock.calls[1][0]).toMatchObject({ symbol: "HYPE" });
  });

  it("keeps a narrative still in the box, and shows the desk's refusal", async () => {
    const onCreate = vi.fn(async (_body: IdeaBody) => {
      throw new ApiError(422, "A long stop sits below the entry.", "stop");
    });
    render(<NewIdeaDialog open markets={MARKETS} seed={null} onOpenChange={() => {}} onCreate={onCreate} />);
    await userEvent.type(screen.getByLabelText("Market"), "ZRO");
    await userEvent.type(screen.getByLabelText("Why"), "Unlock overhang gone after the 20th.");
    await userEvent.type(screen.getByLabelText("Add a narrative"), "unlock");
    await userEvent.click(createButton());
    expect(await screen.findByText("A long stop sits below the entry.")).toBeTruthy();
    expect(onCreate.mock.calls[0][0].tags).toEqual(["unlock"]);
    expect(createButton().disabled).toBe(false);
  });

  it("opens the plan when seeded from the chart", () => {
    render(
      <NewIdeaDialog
        open
        markets={MARKETS}
        seed={{ symbol: "zro", entry: "2.19", stop: "2.08", targets: ["2.40"] }}
        onOpenChange={() => {}}
        onCreate={async () => ({})}
      />,
    );
    expect((screen.getByLabelText("Market") as HTMLInputElement).value).toBe("ZRO");
    expect((screen.getByLabelText("Entry") as HTMLInputElement).value).toBe("2.19");
    expect((screen.getByLabelText("Plan stop") as HTMLInputElement).value).toBe("2.08");
  });
});
