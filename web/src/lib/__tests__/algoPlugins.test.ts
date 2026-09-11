import { describe, expect, it } from "vitest";
import {
  algoOrderKind,
  algoPluginByDeskType,
  CHASE_COI_BASE,
  chaseIcebergPlugin,
  isAlgoClientOrder,
  LADDER_COI_BASE,
  ladderPlugin,
  TWAP_COI_BASE,
  twapPlugin,
} from "@/lib/algoPlugins";

describe("algo plugin COI bands", () => {
  it("recognizes chase and twap client orders from the catalog", () => {
    expect(isAlgoClientOrder(CHASE_COI_BASE)).toBe(true);
    expect(isAlgoClientOrder(TWAP_COI_BASE)).toBe(true);
    expect(isAlgoClientOrder(LADDER_COI_BASE)).toBe(true);
    expect(isAlgoClientOrder(1_000_000_000)).toBe(false);
  });

  it("maps COI to plugin labels", () => {
    expect(algoOrderKind(CHASE_COI_BASE + 1)).toBe("Chase");
    expect(algoOrderKind(TWAP_COI_BASE + 1)).toBe("TWAP");
  });

  it("resolves desk types to plugins", () => {
    expect(algoPluginByDeskType("advanced-twap")?.id).toBe("twap");
    expect(algoPluginByDeskType("chase-iceberg")?.id).toBe("chase-iceberg");
    expect(algoPluginByDeskType("ladder")?.id).toBe("ladder");
  });
});

describe("ladder plugin blockReason", () => {
  const ctx = { sizeNum: 10, decimals: 2, minSz: 0.5, symbol: "ETH" };

  it("blocks without price range", () => {
    expect(ladderPlugin.blockReason(ladderPlugin.defaultState, ctx)).toBe("Set from / to prices");
  });

  it("blocks window above max", () => {
    expect(
      ladderPlugin.blockReason(
        {
          ...ladderPlugin.defaultState,
          priceFrom: "100",
          priceTo: "90",
          window: "25",
        },
        ctx
      )
    ).toBe("Live orders 1–20");
  });

  it("blocks per-order below min", () => {
    expect(
      ladderPlugin.blockReason(
        {
          ...ladderPlugin.defaultState,
          priceFrom: "100",
          priceTo: "90",
          orders: "50",
          window: "10",
        },
        ctx
      )
    ).toBe("Each order ≥ 0.5 — fewer orders or more size");
  });

  it("blocks skewed per-order below min", () => {
    const sized = {
      ...ladderPlugin.defaultState,
      priceFrom: "100",
      priceTo: "90",
      orders: "20",
      window: "10",
    };
    const tight = { sizeNum: 10, decimals: 2, minSz: 0.5, symbol: "ETH" };
    expect(ladderPlugin.blockReason(sized, tight)).toBeNull();
    expect(
      ladderPlugin.blockReason({ ...sized, advanced: true, sizeSkew: "low" }, tight)
    ).toBe("Each order ≥ 0.5 — fewer orders or more size");
  });

  it("blocks advanced variance over cap", () => {
    expect(
      ladderPlugin.blockReason(
        {
          ...ladderPlugin.defaultState,
          priceFrom: "100",
          priceTo: "90",
          advanced: true,
          sizeVarPct: "80",
        },
        ctx
      )
    ).toBe("Size variance 0–50%");
  });
});

describe("chase plugin blockReason", () => {
  const ctx = { sizeNum: 10, decimals: 2, minSz: 1, symbol: "ETH" };

  it("blocks without band", () => {
    expect(
      chaseIcebergPlugin.blockReason(
        { ...chaseIcebergPlugin.defaultState, chaseFloor: "", chaseCeiling: "" },
        ctx
      )
    ).toBe("Set floor / ceiling");
  });

  it("blocks without clip", () => {
    expect(
      chaseIcebergPlugin.blockReason(
        {
          ...chaseIcebergPlugin.defaultState,
          chaseFloor: "90",
          chaseCeiling: "110",
          displayQty: "",
        },
        ctx
      )
    ).toBe("Enter clip size");
  });

  it("allows valid chase params", () => {
    expect(
      chaseIcebergPlugin.blockReason(
        {
          displayQty: "2",
          offsetBps: "4",
          chaseFloor: "90",
          chaseCeiling: "110",
        },
        ctx
      )
    ).toBeNull();
  });
});

describe("twap plugin blockReason", () => {
  const ctx = { sizeNum: 10, decimals: 2, minSz: 0, symbol: "ETH", spot: 100, slipFrac: 0.01 };

  it("blocks without duration", () => {
    expect(
      twapPlugin.blockReason(
        { ...twapPlugin.defaultState, twapHours: "", twapMinutes: "" },
        ctx
      )
    ).toBe("Running time 1m–30d");
  });

  it("blocks advanced twap without valid frequency", () => {
    expect(
      twapPlugin.blockReason(
        {
          ...twapPlugin.defaultState,
          twapAdvanced: true,
          twapFreq: "",
        },
        ctx
      )
    ).toBe("Slice 2s–1h");
  });

  it("blocks venue twap max slip beyond 5%", () => {
    expect(
      twapPlugin.blockReason(
        {
          ...twapPlugin.defaultState,
          twapMaxPrice: "106",
        },
        ctx
      )
    ).toBe("Max 5% from mark");
  });
});
