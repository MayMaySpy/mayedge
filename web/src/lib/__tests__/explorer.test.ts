import { describe, expect, it } from "vitest";
import { accountExplorerUrl, logExplorerUrl } from "@/lib/explorer";

describe("accountExplorerUrl", () => {
  it("builds the Lighter explorer Account index URL", () => {
    expect(accountExplorerUrl(736655)).toBe("https://app.lighter.xyz/explorer/accounts/736655");
  });

  it("skips missing or zero indexes", () => {
    expect(accountExplorerUrl(0)).toBeNull();
    expect(accountExplorerUrl(undefined)).toBeNull();
    expect(accountExplorerUrl("")).toBeNull();
  });
});

describe("logExplorerUrl", () => {
  it("builds the Lighter explorer Log URL from tx_hash", () => {
    expect(
      logExplorerUrl(
        "a3da0c01c4c19979ebfc32c76b86e744255d94f86c28327c3e74c690bea44da8c13357ee6da68754"
      )
    ).toBe(
      "https://app.lighter.xyz/explorer/logs/a3da0c01c4c19979ebfc32c76b86e744255d94f86c28327c3e74c690bea44da8c13357ee6da68754"
    );
  });

  it("skips empty hashes", () => {
    expect(logExplorerUrl("")).toBeNull();
    expect(logExplorerUrl(undefined)).toBeNull();
  });
});
