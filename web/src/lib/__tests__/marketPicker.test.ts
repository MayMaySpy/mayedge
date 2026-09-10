import { describe, expect, it } from "vitest";
import type { Market } from "@/lib/api";
import {
  filterPickerMarkets,
  formatFundingPct,
  lastPrice,
  sortPickerMarkets,
  tokenIconUrl,
} from "@/lib/marketPicker";
import { nextRecents } from "@/lib/recents";

function m(partial: Partial<Market> & { symbol: string }): Market {
  return { market_index: 1, price_decimals: 2, size_decimals: 4, ...partial } as Market;
}

describe("nextRecents", () => {
  it("moves a symbol to the front and caps", () => {
    expect(nextRecents(["ETH", "BTC"], "sol", 3)).toEqual(["SOL", "ETH", "BTC"]);
    expect(nextRecents(["ETH", "BTC", "SOL"], "BTC", 3)).toEqual(["BTC", "ETH", "SOL"]);
    expect(nextRecents(["ETH", "BTC", "SOL"], "LIT", 3)).toEqual(["LIT", "ETH", "BTC"]);
  });
});

describe("filterPickerMarkets", () => {
  const rows = [m({ symbol: "ETH" }), m({ symbol: "BTC" }), m({ symbol: "SOL" })];

  it("filters by query", () => {
    expect(filterPickerMarkets(rows, "et", "all", []).map((x) => x.symbol)).toEqual(["ETH"]);
  });

  it("keeps favorites tab to pinned symbols", () => {
    expect(filterPickerMarkets(rows, "", "favorites", ["SOL", "ETH"]).map((x) => x.symbol)).toEqual([
      "ETH",
      "SOL",
    ]);
  });
});

describe("sortPickerMarkets", () => {
  const rows = [
    m({ symbol: "ETH", volume_24h: 10, change_24h: -1, last_trade_price: 2 }),
    m({ symbol: "BTC", volume_24h: 50, change_24h: 3, last_trade_price: 9 }),
  ];

  it("sorts volume descending", () => {
    expect(sortPickerMarkets(rows, "volume", "desc").map((x) => x.symbol)).toEqual(["BTC", "ETH"]);
  });

  it("sorts change ascending", () => {
    expect(sortPickerMarkets(rows, "change", "asc").map((x) => x.symbol)).toEqual(["ETH", "BTC"]);
  });
});

describe("lastPrice", () => {
  it("prefers last trade", () => {
    expect(lastPrice(m({ symbol: "X", last_trade_price: 3, mark_price: 2 }))).toBe(3);
  });
});

describe("formatFundingPct", () => {
  it("renders hourly rate as percent without scaling", () => {
    expect(formatFundingPct(0.0012)).toBe("+0.0012%");
    expect(formatFundingPct(-0.0032)).toBe("-0.0032%");
  });
});

describe("tokenIconUrl", () => {
  it("uses Lighter asset slug", () => {
    expect(tokenIconUrl("BTC")).toBe("https://assets.lighter.xyz/fe/token/btc.png");
  });
});
