import { memo } from "react";
import { LiquidationHeatTable } from "@/components/widgets/LiquidationHeatTable";
import { RelativeStrengthTable } from "@/components/widgets/RelativeStrengthTable";
import type { LiquidationSummaryHours, Market } from "@/lib/api";

export type ScanTab = "rel" | "liqs";

interface ScanBoardProps {
  tab: ScanTab;
  hours: LiquidationSummaryHours;
  onHoursChange: (hours: LiquidationSummaryHours) => void;
  markets: readonly Market[];
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const ScanBoard = memo(function ScanBoard({
  tab,
  hours,
  onHoursChange,
  markets,
  symbol,
  onSymbolChange,
}: ScanBoardProps) {
  if (tab === "liqs") {
    return (
      <LiquidationHeatTable
        hours={hours}
        onHoursChange={onHoursChange}
        markets={markets}
        symbol={symbol}
        onSymbolChange={onSymbolChange}
      />
    );
  }
  return <RelativeStrengthTable markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />;
});
