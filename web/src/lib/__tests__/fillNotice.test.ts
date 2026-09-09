import { describe, expect, it } from "vitest";
import type { AccountTrade } from "@/lib/api";
import { liveFillNotices, tradeTimestampMs } from "@/lib/fillNotice";

function trade(partial: Partial<AccountTrade> & { trade_id: string }): AccountTrade {
  return {
    market_index: 1,
    symbol: "BTC",
    side: "buy",
    is_maker: false,
    price: "100",
    size: "0.5",
    usd_amount: "50",
    fee: "0",
    pnl: "0",
    type: "trade",
    timestamp: Date.now(),
    ...partial,
  };
}

describe("tradeTimestampMs", () => {
  it("lifts seconds to ms", () => {
    expect(tradeTimestampMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(tradeTimestampMs(1_700_000_000_000)).toBe(1_700_000_000_000);
  });
});

describe("liveFillNotices", () => {
  it("toasts a fresh fill once", () => {
    const now = 1_700_000_000_000;
    const seen = new Set<string>();
    const first = liveFillNotices([trade({ trade_id: "1", timestamp: now - 200 })], {
      seen,
      now,
      armedAt: now - 1_000,
    });
    expect(first).toHaveLength(1);
    expect(first[0]).toMatchObject({ kind: "fill", status: "filled", symbol: "BTC", size: "0.5" });
    const again = liveFillNotices([trade({ trade_id: "1", timestamp: now - 100 })], {
      seen,
      now,
      armedAt: now - 1_000,
    });
    expect(again).toHaveLength(0);
  });

  it("skips snapshot fills from before the session armed", () => {
    const now = 1_700_000_000_000;
    const notices = liveFillNotices([trade({ trade_id: "old", timestamp: now - 60_000 })], {
      seen: new Set(),
      now,
      armedAt: now,
    });
    expect(notices).toHaveLength(0);
  });

  it("treats a missing timestamp as live only after the session is warm", () => {
    const now = 1_700_000_000_000;
    expect(
      liveFillNotices([trade({ trade_id: "snap", timestamp: 0 })], {
        seen: new Set(),
        now,
        armedAt: now,
      })
    ).toHaveLength(0);
    expect(
      liveFillNotices([trade({ trade_id: "live", timestamp: 0 })], {
        seen: new Set(),
        now,
        armedAt: now - 3_000,
      })
    ).toHaveLength(1);
  });
});
