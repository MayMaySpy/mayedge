import { memo, useMemo, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useScanActivity } from "@/lib/liveData";
import { formatFundingPct } from "@/lib/marketPicker";
import {
  ACTIVITY_SORTS,
  rankActivity,
  type ActivitySort,
  type ActivitySortDir,
} from "@/lib/scanActivity";
import { cn, formatPct, formatUsdCompact } from "@/lib/utils";

const SORT_KEY = "mayedge-activity-sort";

type PersistedSort = { key: ActivitySort; dir: ActivitySortDir };

const COLS: { key: ActivitySort | null; label: string; align: "start" | "end"; title?: string }[] = [
  { key: null, label: "Market", align: "start" },
  { key: null, label: "5m", align: "end" },
  { key: "share", label: "Of day", align: "end", title: "The 5m move as a share of the Day range" },
  { key: "volume", label: "Vol", align: "end", title: "Last five minutes against this market's usual five" },
  { key: "oi", label: "OI 5m", align: "end" },
  { key: "funding", label: "Funding", align: "end", title: "Hourly rate, and sigmas from its own 24h median" },
  { key: "premium", label: "Premium", align: "end", title: "Mark over index, and sigmas from its own 24h median" },
];

function loadSort(): PersistedSort {
  try {
    const parsed = JSON.parse(localStorage.getItem(SORT_KEY) ?? "null") as PersistedSort | null;
    if (parsed && ACTIVITY_SORTS.includes(parsed.key) && (parsed.dir === "asc" || parsed.dir === "desc")) {
      return parsed;
    }
  } catch {
    /* ignore */
  }
  return { key: "share", dir: "desc" };
}

function signedClass(value: number | null | undefined) {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-bid" : "text-ask";
}

function sigmas(z: number | null): string {
  return z == null ? "" : `${Math.abs(z).toFixed(1)}σ`;
}

interface ActivityTableProps {
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const ActivityTable = memo(function ActivityTable({ symbol, onSymbolChange }: ActivityTableProps) {
  const rows = useScanActivity();
  const [sort, setSort] = useState<PersistedSort>(loadSort);
  const selected = symbol.toUpperCase();
  const ranked = useMemo(() => rankActivity(rows, sort.key, sort.dir), [rows, sort]);

  const setSortMode = (key: ActivitySort) => {
    const next: PersistedSort =
      sort.key === key ? { key, dir: sort.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" };
    setSort(next);
    try {
      localStorage.setItem(SORT_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="h-8 hover:bg-transparent">
            {COLS.map((col) => {
              const sortKey = col.key;
              return (
                <TableHead
                  key={col.label}
                  title={col.title}
                  className={cn(
                    "font-mono text-xs tracking-wide uppercase",
                    col.align === "end" ? "text-right" : "text-left"
                  )}
                >
                  {sortKey ? (
                    <button
                      type="button"
                      onClick={() => setSortMode(sortKey)}
                      className={cn(
                        "inline-flex items-center gap-0.5 uppercase hover:text-text",
                        col.align === "end" && "ml-auto",
                        sort.key === sortKey && "text-text"
                      )}
                    >
                      {col.label}
                      {sort.key === sortKey ? (sort.dir === "desc" ? " ↓" : " ↑") : null}
                    </button>
                  ) : (
                    col.label
                  )}
                </TableHead>
              );
            })}
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
                className="h-9 cursor-pointer tabular-nums"
                onClick={() => onSymbolChange?.(row.symbol)}
              >
                <TableCell>
                  <div className="flex min-w-0 items-center gap-2">
                    <TokenMark symbol={row.symbol} />
                    <span className="font-sans text-lg text-text">{row.symbol}</span>
                    {row.held && <span className="font-mono text-xs text-warn">held</span>}
                  </div>
                </TableCell>
                <TableCell className={cn("text-right", signedClass(row.move_5m))}>
                  {formatPct(row.move_5m)}
                </TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {row.share == null ? "—" : `${Math.round(row.share * 100)}%`}
                </TableCell>
                <TableCell className="text-right">
                  {row.vol_x == null ? "—" : `${row.vol_x.toFixed(1)}×`}
                </TableCell>
                <TableCell className={cn("text-right", signedClass(row.oi_5m))}>
                  {row.oi_5m == null ? "—" : formatPct(row.oi_5m)}
                  {row.oi_usd_5m ? (
                    <span className="ml-1 text-muted-foreground">
                      {formatUsdCompact(Math.abs(row.oi_usd_5m))}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell className={cn("text-right", signedClass(-row.funding))}>
                  {formatFundingPct(row.funding)}
                  <span className="ml-1 text-muted-foreground">{sigmas(row.funding_z)}</span>
                </TableCell>
                <TableCell className={cn("text-right", signedClass(row.premium))}>
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
