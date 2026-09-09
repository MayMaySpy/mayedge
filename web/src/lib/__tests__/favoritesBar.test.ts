import { describe, expect, it } from "vitest";
import type { Market } from "@/lib/api";
import { favChangeTone, favPriceLabel, insertIndexAtX, moveIdToIndex, scrollFadeX } from "@/lib/favoritesBar";

function m(partial: Partial<Market> & { symbol: string }): Market {
  return { market_index: 1, price_decimals: 2, size_decimals: 4, ...partial } as Market;
}

describe("favPriceLabel", () => {
  it("formats last trade with market decimals", () => {
    expect(favPriceLabel(m({ symbol: "BTC", last_trade_price: 78549.7, price_decimals: 1 }))).toBe(
      "78,549.7"
    );
  });

  it("falls back when there is no last", () => {
    expect(favPriceLabel(m({ symbol: "X" }))).toBe("—");
  });
});

describe("favChangeTone", () => {
  it("maps signed change to bid/ask", () => {
    expect(favChangeTone(1.96)).toBe("bid");
    expect(favChangeTone(-0.72)).toBe("ask");
    expect(favChangeTone(0)).toBe("muted");
  });
});

describe("scrollFadeX", () => {
  it("fades the overflowing edge and shows the chevron", () => {
    expect(scrollFadeX(0, 200, 400)).toEqual({ fadeL: 0, fadeR: 24, showRight: true });
    expect(scrollFadeX(100, 200, 400)).toEqual({ fadeL: 24, fadeR: 24, showRight: true });
    expect(scrollFadeX(200, 200, 400)).toEqual({ fadeL: 24, fadeR: 0, showRight: false });
  });

  it("stays plain when content fits", () => {
    expect(scrollFadeX(0, 400, 200)).toEqual({ fadeL: 0, fadeR: 0, showRight: false });
  });
});

describe("favorite reorder", () => {
  const rects = [
    { id: "BTC", left: 0, width: 100 },
    { id: "ETH", left: 100, width: 100 },
    { id: "SOL", left: 200, width: 100 },
  ];

  it("inserts among the chips that are not being dragged", () => {
    expect(insertIndexAtX(30, rects, "ETH")).toBe(0);
    expect(insertIndexAtX(80, rects, "ETH")).toBe(1);
    expect(insertIndexAtX(260, rects, "ETH")).toBe(2);
  });

  it("moves ETH without flipping back on its own midpoint", () => {
    expect(moveIdToIndex(["BTC", "ETH", "SOL"], "ETH", 0)).toEqual(["ETH", "BTC", "SOL"]);
    expect(moveIdToIndex(["BTC", "ETH", "SOL"], "ETH", 1)).toEqual(["BTC", "ETH", "SOL"]);
    expect(moveIdToIndex(["BTC", "ETH", "SOL"], "ETH", 2)).toEqual(["BTC", "SOL", "ETH"]);
  });
});
