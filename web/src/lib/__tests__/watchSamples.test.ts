import { afterEach, describe, expect, it } from "vitest";
import {
  clearWatchSamples,
  getWatchSamples,
  replaceWatchSamples,
  rollWatch,
  snapshotWatchSamples,
} from "@/lib/watchSamples";

describe("rollWatch", () => {
  afterEach(() => {
    clearWatchSamples();
  });

  it("records a 1s Last for each Watchlist Market", () => {
    rollWatch(["BTC", "ETH"], { BTC: 100, ETH: 200 }, 1_700_000_000);
    expect(getWatchSamples("BTC")).toEqual([{ t: 1_700_000_000, px: 100 }]);
    expect(getWatchSamples("ETH")).toEqual([{ t: 1_700_000_000, px: 200 }]);
  });

  it("skips a Market with no Last", () => {
    rollWatch(["BTC"], { BTC: null }, 1_700_000_000);
    expect(getWatchSamples("BTC")).toEqual([]);
  });

  it("updates the same second in place", () => {
    rollWatch(["BTC"], { BTC: 100 }, 50);
    rollWatch(["BTC"], { BTC: 101 }, 50);
    expect(getWatchSamples("BTC")).toEqual([{ t: 50, px: 101 }]);
  });

  it("drops the oldest samples when the ring is full", () => {
    rollWatch(["BTC"], { BTC: 1 }, 1, 2);
    rollWatch(["BTC"], { BTC: 2 }, 2, 2);
    rollWatch(["BTC"], { BTC: 3 }, 3, 2);
    expect(getWatchSamples("BTC")).toEqual([
      { t: 2, px: 2 },
      { t: 3, px: 3 },
    ]);
  });

  it("drops rings for Markets that left the Watchlist", () => {
    rollWatch(["BTC", "ETH"], { BTC: 1, ETH: 2 }, 1);
    rollWatch(["BTC"], { BTC: 1 }, 2);
    expect(getWatchSamples("ETH")).toEqual([]);
  });

  it("round-trips a Path snapshot", () => {
    rollWatch(["BTC"], { BTC: 100 }, 10);
    const snap = snapshotWatchSamples();
    expect(snap).toEqual({ BTC: [{ t: 10, px: 100 }] });
    clearWatchSamples();
    replaceWatchSamples(snap);
    expect(getWatchSamples("BTC")).toEqual([{ t: 10, px: 100 }]);
  });
});
