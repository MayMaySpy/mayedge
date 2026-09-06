import { describe, expect, it, afterEach } from "vitest";
import { getTradingReadySnapshot } from "@/hooks/useTradingReady";
import { setBookSynced, setFeedHealth } from "@/lib/liveData";

describe("getTradingReadySnapshot", () => {
  afterEach(() => {
    setFeedHealth({
      market_ws: "down",
      account_ws: "down",
      last_msg_at: 0,
      account_last_msg_at: 0,
      trade_subs: 0,
      trade_subs_target: 0,
    });
    setBookSynced(false);
  });

  it("returns the same object when the store is unchanged", () => {
    const a = getTradingReadySnapshot(false);
    const b = getTradingReadySnapshot(false);
    expect(a).toBe(b);
    expect(a.ready).toBe(false);
    expect(a.reason).toBe("Reconnecting");
  });

  it("blocks when account feed is not live", () => {
    setFeedHealth({ market_ws: "live", account_ws: "stale" });
    setBookSynced(true);
    const snap = getTradingReadySnapshot(true);
    expect(snap.ready).toBe(false);
    expect(snap.reason).toBe("Account feed stale");
  });
});
