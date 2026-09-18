import { describe, expect, it } from "vitest";
import { listWatchChips } from "@/lib/watchChips";
import { WATCH_LINE_COLORS } from "@/lib/watchPath";

describe("listWatchChips", () => {
  it("keeps Watchlist add order even when Path ranks differ", () => {
    expect(
      listWatchChips(["BTC", "ETH", "SOL"], { BTC: 0.1, ETH: 0.4, SOL: -0.2 }).map((c) => c.symbol)
    ).toEqual(["BTC", "ETH", "SOL"]);
  });

  it("attaches Path without using it to order", () => {
    expect(listWatchChips(["ETH", "BTC"], { ETH: -0.2, BTC: 1.4 })).toEqual([
      { symbol: "ETH", color: WATCH_LINE_COLORS[0], pct: -0.2 },
      { symbol: "BTC", color: WATCH_LINE_COLORS[1], pct: 1.4 },
    ]);
  });

  it("treats missing Path as unknown, not 0", () => {
    expect(listWatchChips(["BTC"], {}).map((c) => c.pct)).toEqual([null]);
  });
});
