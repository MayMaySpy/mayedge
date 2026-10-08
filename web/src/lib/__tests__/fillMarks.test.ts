import { describe, expect, it } from "vitest";
import { fillMarks, type FillTrade } from "@/lib/fillMarks";

function trade(partial: Partial<FillTrade> & Pick<FillTrade, "trade_id" | "timestamp">): FillTrade {
  return {
    market_index: 1,
    side: "buy",
    price: "100",
    size: "1",
    ...partial,
  };
}

describe("fillMarks", () => {
  it("puts a buy on the candle that contains the fill", () => {
    const marks = fillMarks([trade({ trade_id: "a", timestamp: 125, price: "101.5", size: "2" })], 1, 60);
    expect(marks).toEqual([{ time: 120, side: "buy", size: 2, price: 101.5, count: 1 }]);
  });

  it("weights price by size when several fills share a candle and a side", () => {
    const marks = fillMarks(
      [
        trade({ trade_id: "a", timestamp: 130, price: "100", size: "1" }),
        trade({ trade_id: "b", timestamp: 140, price: "110", size: "3" }),
      ],
      1,
      60,
    );
    expect(marks).toEqual([{ time: 120, side: "buy", size: 4, price: 107.5, count: 2 }]);
  });

  it("keeps buy and sell apart on the same candle, and ignores other markets and duplicate ids", () => {
    const marks = fillMarks(
      [
        trade({ trade_id: "a", timestamp: 1_700_000_000_500, side: "sell", price: "50", size: "2" }),
        trade({ trade_id: "a", timestamp: 1_700_000_000_500, side: "sell", price: "99", size: "9" }),
        trade({ trade_id: "b", timestamp: 1_700_000_010, side: "buy", price: "40", size: "1" }),
        trade({ trade_id: "c", timestamp: 1_700_000_010, market_index: 2, side: "buy", price: "1", size: "1" }),
      ],
      1,
      60,
    );
    expect(marks).toEqual([
      { time: 1_699_999_980, side: "buy", size: 1, price: 40, count: 1 },
      { time: 1_699_999_980, side: "sell", size: 2, price: 50, count: 1 },
    ]);
  });
});
