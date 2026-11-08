// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deskFirstCandles } from "@/lib/startup";

describe("deskFirstCandles", () => {
  it("asks for the selected Market's drawn timeframe on the desk", () => {
    expect(deskFirstCandles("/ETH", "price", "1m")).toEqual({ symbol: "ETH", resolution: "1m", count: 500 });
    expect(deskFirstCandles("/ETH", "price", "1h")).toEqual({ symbol: "ETH", resolution: "1h", count: 500 });
  });

  it("asks for an hour of seconds on a seconds timeframe", () => {
    expect(deskFirstCandles("/BTC", "price", "1s")).toEqual({ symbol: "BTC", resolution: "1s", count: 3600 });
  });

  it("asks for nothing when the chart shows no price or the page is not the desk", () => {
    expect(deskFirstCandles("/ETH", "scan", "1m")).toBeNull();
    expect(deskFirstCandles("/journal", "price", "1m")).toBeNull();
    expect(deskFirstCandles("/watch", "price", "1m")).toBeNull();
  });
});

describe("desk load gate", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    window.history.replaceState(null, "", "/ETH");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  async function freshStartup() {
    const { api: freshApi } = await import("@/lib/api");
    const candles = vi.spyOn(freshApi, "candles").mockResolvedValue([]);
    const startup = await import("@/lib/startup");
    return { startup, candles };
  }

  it("is open when the desk was never started", async () => {
    const { startup } = await freshStartup();
    const run = vi.fn();
    startup.afterChart(run);
    expect(run).toHaveBeenCalledOnce();
  });

  it("sends the chart's candles first and holds the rest until the chart draws", async () => {
    const { startup, candles } = await freshStartup();
    startup.startDesk();
    expect(candles).toHaveBeenCalledWith("ETH", "1m", 500);
    const run = vi.fn();
    startup.afterChart(run);
    expect(run).not.toHaveBeenCalled();
    startup.chartDrawn();
    await vi.advanceTimersByTimeAsync(200);
    expect(run).toHaveBeenCalledOnce();
  });

  it("lets the rest load after the fallback when the chart never draws", async () => {
    const { startup } = await freshStartup();
    startup.startDesk();
    const run = vi.fn();
    startup.afterChart(run);
    await vi.advanceTimersByTimeAsync(startup.STARTUP_FALLBACK_MS - 1);
    expect(run).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(startup.isChartDrawn()).toBe(true);
    await vi.runOnlyPendingTimersAsync();
    expect(run).toHaveBeenCalledOnce();
  });

  it("shares one candle request between the prefetch and the chart", async () => {
    const { startup, candles } = await freshStartup();
    startup.startDesk();
    await startup.loadCandles("ETH", "1m", 500);
    await startup.loadCandles("eth", "1m", 500);
    expect(candles).toHaveBeenCalledOnce();
  });
});
