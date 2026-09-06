import { describe, expect, it } from "vitest";
import {
  applyBookDelta,
  applyBookSnapshot,
  clearBook,
  isBookSynced,
} from "@/lib/liveData";

describe("applyBookDelta", () => {
  it("returns false and clears sync on seq gap", () => {
    clearBook();
    applyBookSnapshot({ bids: [{ price: "100", size: "1" }], asks: [{ price: "101", size: "1" }] }, 10);
    expect(isBookSynced()).toBe(true);

    const ok = applyBookDelta(
      { bids: [{ price: "100", size: "2" }], asks: [] },
      { seq: 11, prevSeq: 9 }
    );
    expect(ok).toBe(false);
    expect(isBookSynced()).toBe(false);
  });
});
