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
import { useScanActivity } from "@/lib/liveData";
import { formatFundingPct } from "@/lib/marketPicker";
import { ACTIVITY_SORTS, rankActivity, type ActivitySort } from "@/lib/scanActivity";
import { useStoredSort, type SortCol } from "@/lib/tableSort";
import { cn, formatPct, formatUsdCompact, signClass } from "@/lib/utils";

const SORT_KEY = "mayedge-activity-sort";

const COLS: readonly SortCol<ActivitySort>[] = [
  { key: null, label: "Market", align: "start" },
  { key: null, label: "5m", align: "end" },
  { key: "share", label: "Of day", align: "end", title: "The 5m move as a share of the Day range", hideBelow: "lg" },
  { key: "volume", label: "Vol", align: "end", title: "Last five minutes against this market's usual five", hideBelow: "sm" },
  { key: "oi", label: "OI 5m", align: "end", hideBelow: "sm" },
  { key: "funding", label: "Funding", align: "end", title: "Hourly rate, and sigmas from its own 24h median", hideBelow: "md" },
  { key: "premium", label: "Premium", align: "end", title: "Mark over index, and sigmas from its own 24h median", hideBelow: "md" },
];

function sigmas(z: number | null): string {
  return z == null ? "" : `${Math.abs(z).toFixed(1)}σ`;
}

interface ActivityTableProps {
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const ActivityTable = memo(function ActivityTable({ symbol, onSymbolChange }: ActivityTableProps) {
  const rows = useScanActivity();
  const [sort, setSortMode] = useStoredSort(SORT_KEY, ACTIVITY_SORTS, "share");
  const selected = symbol.toUpperCase();
  const ranked = useMemo(() => rankActivity(rows, sort.key, sort.dir), [rows, sort]);

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="hover:bg-transparent">
            <SortableHeads cols={COLS} sort={sort} onSort={setSortMode} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {ranked.length === 0 ? (
            <TableRow>
              <TableCell colSpan={COLS.length} className="px-3 py-8 text-center text-muted-foreground">
                No liquid markets yet
              </TableCell>
            </TableRow>
          ) : (
            ranked.map((row) => (
              <TableRow
                key={row.market_index}
                data-state={row.symbol.toUpperCase() === selected ? "selected" : undefined}
                className="cursor-pointer"
                onClick={() => onSymbolChange?.(row.symbol)}
              >
                <TableCell>
                  <div className="flex min-w-0 items-center gap-2">
                    <TokenMark symbol={row.symbol} className="size-4" />
                    <TableName className="text-text">{row.symbol}</TableName>
                    {row.held && <span className="text-xs text-warn">held</span>}
                  </div>
                </TableCell>
                <TableCell className={cn("text-right", signClass(row.move_5m))}>
                  {formatPct(row.move_5m)}
                </TableCell>
                <TableCell hideBelow="lg" className="text-right text-muted-foreground">
                  {row.share == null ? "—" : `${Math.round(row.share * 100)}%`}
                </TableCell>
                <TableCell hideBelow="sm" className="text-right">
                  {row.vol_x == null ? "—" : `${row.vol_x.toFixed(1)}×`}
                </TableCell>
                <TableCell hideBelow="sm" className={cn("text-right", signClass(row.oi_5m))}>
                  {row.oi_5m == null ? "—" : formatPct(row.oi_5m)}
                  {row.oi_usd_5m ? (
                    <span className="ml-1 text-muted-foreground">
                      {formatUsdCompact(Math.abs(row.oi_usd_5m))}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell hideBelow="md" className={cn("text-right", signClass(-row.funding))}>
                  {formatFundingPct(row.funding)}
                  <span className="ml-1 text-muted-foreground">{sigmas(row.funding_z)}</span>
                </TableCell>
                <TableCell hideBelow="md" className={cn("text-right", signClass(row.premium))}>
                  {formatPct(row.premium)}
                  <span className="ml-1 text-muted-foreground">{sigmas(row.premium_z)}</span>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
});
