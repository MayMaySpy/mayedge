import { describe, expect, it } from "vitest";
import { priceFormat } from "@/components/widgets/chart/chartFormat";
import { formatNumber, formatPct, formatPrice, formatSigned, formatSize, formatUsd } from "@/lib/utils";

describe("desk number format", () => {
  it("prints `.` decimals and `,` thousands whatever the browser's locale", () => {
    expect(formatPrice(1363.16, 2)).toBe("1,363.16");
    expect(formatPrice("3.4166", 4)).toBe("3.4166");
    expect(formatSize(12_500.5)).toBe("12,500.5");
    expect(formatSigned(-53.37)).toBe("-53.37");
    expect(formatPct(2.34)).toBe("+2.34%");
    expect(formatNumber(0.5, 0, 6)).toBe("0.5");
  });

  it("puts the dollar sign in front, after any minus", () => {
    expect(formatUsd(1363.16)).toBe("$1,363.16");
    expect(formatUsd(-4.2)).toBe("-$4.20");
    expect(formatUsd(null)).toBe("—");
  });

  it("gives the chart's price axis the same format", () => {
    const fmt = priceFormat(1);
    expect(fmt.formatter(82759.4)).toBe("82,759.4");
    expect(priceFormat(4).formatter(3.435)).toBe("3.4350");
    expect(fmt.minMove).toBe(0.1);
  });
});
