import { describe, expect, it } from "vitest";
import {
  algoAvgFillPrice,
  algoCanResume,
  algoIsPaused,
  algoReasonLabel,
  algoResumeNotice,
} from "@/lib/algos";

describe("algoAvgFillPrice", () => {
  it("is null with no priced fills", () => {
    expect(algoAvgFillPrice(undefined)).toBeNull();
    expect(algoAvgFillPrice([])).toBeNull();
    expect(algoAvgFillPrice([{ price: "0", qty: "10" }])).toBeNull();
  });

  it("is the size-weighted average of fills", () => {
    expect(
      algoAvgFillPrice([
        { price: "100", qty: "1" },
        { price: "110", qty: "3" },
      ]),
    ).toBe(107.5);
  });
});

describe("algoCanResume", () => {
  it("is true for paused and error so vanished clips can retry", () => {
    expect(algoCanResume("paused")).toBe(true);
    expect(algoCanResume("error")).toBe(true);
    expect(algoCanResume("running")).toBe(false);
    expect(algoIsPaused("error")).toBe(false);
  });
});

describe("algoReasonLabel", () => {
  it("labels a vanished clip as retrying", () => {
    expect(algoReasonLabel("unproven_missing_clip")).toBe("Clip vanished — retrying");
  });

  it("labels a trade sync stall as retrying", () => {
    expect(algoReasonLabel("trades_reconcile_failed")).toBe("Trade sync failed — retrying");
  });
});

describe("algoResumeNotice", () => {
  it("does not claim success when trade sync is still failing", () => {
    expect(
      algoResumeNotice({
        algo_id: "ch-1",
        status: "error",
        error: "trades_reconcile_failed",
      })
    ).toEqual({
      tone: "err",
      title: "Resume failed",
      description: "Trade sync failed — retrying",
    });
  });

  it("warns when resume left the job retrying trade sync", () => {
    expect(
      algoResumeNotice({
        algo_id: "ch-1",
        status: "running",
        reason: "trades_reconcile_failed",
      })
    ).toEqual({
      tone: "warn",
      title: "ch-1",
      description: "Trade sync failed — retrying",
    });
  });

  it("confirms only when the job is actually quoting again", () => {
    expect(algoResumeNotice({ algo_id: "ch-1", status: "running", reason: "rest" })).toEqual({
      tone: "ok",
      title: "ch-1 resumed",
      description: "",
    });
  });
});
