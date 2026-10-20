// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PageNav } from "@/components/PageNav";

afterEach(cleanup);

describe("PageNav", () => {
  it("links the desk and the other page, and titles the current one", () => {
    render(<PageNav current="Journal" />);
    expect(screen.getByRole("heading", { name: "Journal" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Portfolio" }).getAttribute("href")).toBe("/portfolio");
    expect(screen.getByRole("link", { name: "Desk" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Journal" })).toBeNull();
  });
});
