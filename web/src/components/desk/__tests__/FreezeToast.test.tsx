// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FillNotice } from "@/components/desk/FillNotice";

const TEXT =
  "Desk was frozen 14m (02:10–02:24 UTC). Trails, Planner trailing parts and Auto kill were not watching; venue stops held. 2 Positions open, uPnL −$120.";

afterEach(cleanup);

describe("freeze toast", () => {
  it("renders the freeze text", () => {
    render(<FillNotice title={TEXT} description="" tone="warn" />);
    expect(screen.getByText(TEXT)).toBeTruthy();
  });
});
