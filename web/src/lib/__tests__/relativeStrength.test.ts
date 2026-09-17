import { describe, expect, it } from "vitest";
import type { Market } from "@/lib/api";
import { rankRelativeStrength } from "@/lib/relativeStrength";

function m(partial: Partial<Market> & { symbol: string }): Market {
  return { market_index: 1, price_decimals: 2, size_decimals: 4, ...partial } as Market;
}

describe("rankRelativeStrength", () => {
  it("is Daily Change minus BTC Daily Change, and BTC versus itself is 0", () => {
    const board = rankRelativeStrength([
      m({ symbol: "BTC", market_index: 1, change_24h: 2 }),
      m({ symbol: "ETH", market_index: 2, change_24h: 5 }),
    ]);

    expect(board.numeraireSymbol).toBe("BTC");
    expect(board.numeraireChange24h).toBe(2);

    const btc = board.rows.find((r) => r.symbol === "BTC");
    const eth = board.rows.find((r) => r.symbol === "ETH");
    expect(btc).toEqual(
      expect.objectContaining({
        marketIndex: 1,
        change24h: 2,
        relativeStrength: 0,
        isNumeraire: true,
      })
    );
    expect(eth).toEqual(
      expect.objectContaining({
        marketIndex: 2,
        change24h: 5,
        relativeStrength: 3,
        isNumeraire: false,
      })
    );
  });

  it("copies funding rate onto the row", () => {
    const board = rankRelativeStrength([
      m({ symbol: "BTC", market_index: 1, change_24h: 2, funding_rate: 0.0012 }),
      m({ symbol: "ETH", market_index: 2, change_24h: 5, funding_rate: -0.0032 }),
    ]);
    expect(board.rows.find((r) => r.symbol === "ETH")?.fundingRate).toBe(-0.0032);
    expect(board.rows.find((r) => r.symbol === "BTC")?.fundingRate).toBe(0.0012);
  });

  it("is negative when the Market falls more than BTC", () => {
    const board = rankRelativeStrength([
      m({ symbol: "BTC", market_index: 1, change_24h: -5 }),
      m({ symbol: "ETH", market_index: 2, change_24h: -10 }),
    ]);
    const eth = board.rows.find((r) => r.symbol === "ETH");
    expect(eth?.relativeStrength).toBe(-5);
  });

  it("leaves Relative Strength unknown when a Market has no Daily Change", () => {
    const board = rankRelativeStrength([
      m({ symbol: "BTC", market_index: 1, change_24h: 2 }),
      m({ symbol: "ETH", market_index: 2, change_24h: 5 }),
      m({ symbol: "SOL", market_index: 3 }),
    ]);
    const sol = board.rows.find((r) => r.symbol === "SOL");
    const eth = board.rows.find((r) => r.symbol === "ETH");
    expect(sol?.relativeStrength).toBeNull();
    expect(eth?.relativeStrength).toBe(3);
  });

  it("makes every Relative Strength unknown when BTC is missing", () => {
    const board = rankRelativeStrength([
      m({ symbol: "ETH", market_index: 2, change_24h: 5, volume_24h: 10, open_interest: 20 }),
    ]);
    expect(board.numeraireChange24h).toBeNull();
    expect(board.rows).toEqual([
      {
        symbol: "ETH",
        marketIndex: 2,
        change24h: 5,
        relativeStrength: null,
        volume24h: 10,
        openInterest: 20,
        fundingRate: null,
        isNumeraire: false,
      },
    ]);
  });

  it("makes every Relative Strength unknown when BTC has no Daily Change", () => {
    const board = rankRelativeStrength([
      m({ symbol: "BTC", market_index: 1, volume_24h: 100, open_interest: 200 }),
      m({ symbol: "ETH", market_index: 2, change_24h: 5, volume_24h: 10, open_interest: 20 }),
    ]);
    expect(board.numeraireChange24h).toBeNull();
    expect(board.rows.find((r) => r.symbol === "ETH")?.relativeStrength).toBeNull();
    expect(board.rows.find((r) => r.symbol === "BTC")?.relativeStrength).toBeNull();
    expect(board.rows.find((r) => r.symbol === "ETH")?.volume24h).toBe(10);
    expect(board.rows.find((r) => r.symbol === "ETH")?.openInterest).toBe(20);
  });

  it("keeps one row per symbol and prefers the perp", () => {
    const board = rankRelativeStrength([
      m({ symbol: "BTC", market_index: 1, change_24h: 2 }),
      m({ symbol: "ETH", market_index: 9, change_24h: 4, market_type: "spot", is_perp: false }),
      m({ symbol: "ETH", market_index: 2, change_24h: 5, market_type: "perp", is_perp: true }),
    ]);
    const ethRows = board.rows.filter((r) => r.symbol === "ETH");
    expect(ethRows).toHaveLength(1);
    expect(ethRows[0].marketIndex).toBe(2);
    expect(ethRows[0].relativeStrength).toBe(3);
  });

  it("sorts strongest Relative Strength first and tie-breaks by symbol", () => {
    const board = rankRelativeStrength([
      m({ symbol: "SOL", market_index: 3, change_24h: 4 }),
      m({ symbol: "ETH", market_index: 2, change_24h: 8 }),
      m({ symbol: "BTC", market_index: 1, change_24h: 2 }),
      m({ symbol: "AAVE", market_index: 4, change_24h: 8 }),
    ]);
    expect(board.rows.map((r) => r.symbol)).toEqual(["AAVE", "ETH", "SOL", "BTC"]);
    expect(board.rows.map((r) => r.relativeStrength)).toEqual([6, 6, 2, 0]);
  });

  it("sorts unknown Relative Strength last in both directions", () => {
    const markets = [
      m({ symbol: "BTC", market_index: 1, change_24h: 2 }),
      m({ symbol: "ETH", market_index: 2, change_24h: 5 }),
      m({ symbol: "SOL", market_index: 3 }),
    ];
    const desc = rankRelativeStrength(markets, { sort: "rs", dir: "desc" });
    const asc = rankRelativeStrength(markets, { sort: "rs", dir: "asc" });
    expect(desc.rows.map((r) => r.symbol)).toEqual(["ETH", "BTC", "SOL"]);
    expect(asc.rows.map((r) => r.symbol)).toEqual(["BTC", "ETH", "SOL"]);
  });

  it("sorts by 24h volume descending", () => {
    const board = rankRelativeStrength(
      [
        m({ symbol: "ETH", market_index: 2, change_24h: 5, volume_24h: 10 }),
        m({ symbol: "BTC", market_index: 1, change_24h: 2, volume_24h: 50 }),
      ],
      { sort: "volume", dir: "desc" }
    );
    expect(board.rows.map((r) => r.symbol)).toEqual(["BTC", "ETH"]);
  });

  it("sorts by open interest descending", () => {
    const board = rankRelativeStrength(
      [
        m({ symbol: "ETH", market_index: 2, change_24h: 5, open_interest: 10 }),
        m({ symbol: "BTC", market_index: 1, change_24h: 2, open_interest: 50 }),
      ],
      { sort: "oi", dir: "desc" }
    );
    expect(board.rows.map((r) => r.symbol)).toEqual(["BTC", "ETH"]);
  });
});
