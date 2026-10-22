import { memo, useMemo } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import { SortableHeads } from "@/components/widgets/SortableHeads";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableName,
  TableRow,
} from "@/components/ui/table";
import type { Market } from "@/lib/api";
import { formatFundingPct } from "@/lib/marketPicker";
import { rankRelativeStrength, type RsSort } from "@/lib/relativeStrength";
import { useSelectedRowInView } from "@/lib/scanScroll";
import { useStoredSort, type SortCol } from "@/lib/tableSort";
import { cn, formatPct, formatUsdCompact, signClass } from "@/lib/utils";

const SORT_KEY = "mayedge-rs-sort";

const SORTS: readonly RsSort[] = ["rs", "volume", "oi"];

const COLS: readonly SortCol<RsSort>[] = [
  { key: null, label: "#", align: "end", hideBelow: "lg" },
  { key: null, label: "Market", align: "start" },
  { key: null, label: "24h", align: "end" },
  { key: "rs", label: "vs BTC", align: "end" },
  { key: "volume", label: "Volume", align: "end", hideBelow: "sm" },
  { key: "oi", label: "OI", align: "end", hideBelow: "md" },
  { key: null, label: "Funding", align: "end", hideBelow: "md" },
];

function fundingClass(rate: number | null | undefined) {
  if (rate == null || rate === 0) return "text-muted-foreground";
  return rate > 0 ? "text-ask" : "text-bid";
}

interface RelativeStrengthTableProps {
  markets: readonly Market[];
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const RelativeStrengthTable = memo(function RelativeStrengthTable({
  markets,
  symbol,
  onSymbolChange,
}: RelativeStrengthTableProps) {
  const [sort, setSortMode] = useStoredSort(SORT_KEY, SORTS, "rs");
  const selected = symbol.toUpperCase();

  const board = useMemo(
    () => rankRelativeStrength(markets, { sort: sort.key, dir: sort.dir }),
    [markets, sort]
  );
  const { scrollerRef, rowRef } = useSelectedRowInView(
    selected,
    board.rows.some((r) => r.symbol.toUpperCase() === selected)
  );

  return (
    <div ref={scrollerRef} className="min-h-0 flex-1 overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="hover:bg-transparent">
            <SortableHeads cols={COLS} sort={sort} onSort={setSortMode} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {board.rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={COLS.length} className="px-3 py-8 text-center text-muted-foreground">
                No markets
              </TableCell>
            </TableRow>
          ) : (
            board.rows.map((row, i) => {
              const isSelected = row.symbol.toUpperCase() === selected;
              return (
                <TableRow
                  key={row.marketIndex}
                  ref={rowRef(row.symbol)}
                  data-state={isSelected ? "selected" : undefined}
                  className="cursor-pointer"
                  onClick={() => onSymbolChange?.(row.symbol)}
                >
                  <TableCell hideBelow="lg" className="text-right text-muted-foreground">{i + 1}</TableCell>
                  <TableCell>
                    <div className="flex min-w-0 items-center gap-2">
                      <TokenMark symbol={row.symbol} className="size-4" />
                      <TableName className={row.isNumeraire ? "text-muted-foreground" : "text-text"}>
                        {row.symbol}
                      </TableName>
                    </div>
                  </TableCell>
                  <TableCell className={cn("text-right", signClass(row.change24h))}>
                    {formatPct(row.change24h)}
                  </TableCell>
                  <TableCell className={cn("text-right", signClass(row.relativeStrength))}>
                    {formatPct(row.relativeStrength)}
                  </TableCell>
                  <TableCell hideBelow="sm" className="text-right text-muted-foreground">
                    {formatUsdCompact(row.volume24h) || "—"}
                  </TableCell>
                  <TableCell hideBelow="md" className="text-right text-muted-foreground">
                    {formatUsdCompact(row.openInterest) || "—"}
                  </TableCell>
                  <TableCell hideBelow="md" className={cn("text-right", fundingClass(row.fundingRate))}>
                    {formatFundingPct(row.fundingRate)}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
});
