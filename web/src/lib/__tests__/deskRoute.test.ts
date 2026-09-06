import { describe, expect, it } from "vitest";
import { DEFAULT_SYMBOL, parsePath, toPath } from "@/lib/deskRoute";

describe("parsePath", () => {
  it("reads /ETH as ETH", () => {
    expect(parsePath("/ETH")).toEqual({ symbol: "ETH" });
  });

  it("rewrites legacy /lighter/ETH to /ETH", () => {
    expect(parsePath("/lighter/ETH")).toEqual({ symbol: "ETH", rewriteTo: "/ETH" });
  });

  it("rewrites legacy /hyperliquid/ETH to /ETH", () => {
    expect(parsePath("/hyperliquid/ETH")).toEqual({ symbol: "ETH", rewriteTo: "/ETH" });
  });

  it("defaults root to LIT", () => {
    expect(parsePath("/")).toEqual({ symbol: DEFAULT_SYMBOL });
  });
});

describe("toPath", () => {
  it("uppercases symbol", () => {
    expect(toPath("eth")).toBe("/ETH");
  });
});
