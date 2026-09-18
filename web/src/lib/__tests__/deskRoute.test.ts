import { describe, expect, it } from "vitest";
import { DEFAULT_SYMBOL, isWatchPath, parsePath, toPath } from "@/lib/deskRoute";

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

  it("does not treat /watch as a Market", () => {
    expect(parsePath("/watch")).toEqual({ symbol: DEFAULT_SYMBOL });
    expect(parsePath("/WATCH")).toEqual({ symbol: DEFAULT_SYMBOL });
  });
});

describe("isWatchPath", () => {
  it("is only the Watch window path", () => {
    expect(isWatchPath("/watch")).toBe(true);
    expect(isWatchPath("/WATCH")).toBe(true);
    expect(isWatchPath("/watch/")).toBe(true);
    expect(isWatchPath("/ETH")).toBe(false);
    expect(isWatchPath("/")).toBe(false);
  });
});

describe("toPath", () => {
  it("uppercases symbol", () => {
    expect(toPath("eth")).toBe("/ETH");
  });
});
