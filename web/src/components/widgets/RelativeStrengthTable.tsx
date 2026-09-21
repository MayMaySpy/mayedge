import { memo, useEffect, useMemo, useRef, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Market } from "@/lib/api";
import { formatFundingPct } from "@/lib/marketPicker";
import {
  rankRelativeStrength,
  type RsSort,
  type RsSortDir,
} from "@/lib/relativeStrength";
import { alignRowToTop } from "@/lib/scanScroll";
import { cn, formatPct, formatUsdCompact } from "@/lib/utils";

const SORT_KEY = "mayedge-rs-sort";

type PersistedSort = { key: RsSort; dir: RsSortDir };

const COLS: {
  key: RsSort | null;
  label: string;
  align: "start" | "end";
}[] = [
  { key: null, label: "#", align: "end" },
  { key: null, label: "Market", align: "start" },
  { key: null, label: "24h", align: "end" },
  { key: "rs", label: "vs BTC", align: "end" },
  { key: "volume", label: "Volume", align: "end" },
  { key: "oi", label: "OI", align: "end" },
  { key: null, label: "Funding", align: "end" },
];

function loadSort(): PersistedSort {
  try {
    const raw = localStorage.getItem(SORT_KEY);
    if (!raw) return { key: "rs", dir: "desc" };
    const parsed = JSON.parse(raw) as PersistedSort;
    if (
      (parsed?.key === "rs" || parsed?.key === "volume" || parsed?.key === "oi") &&
      (parsed?.dir === "asc" || parsed?.dir === "desc")
    ) {
      return parsed;
    }
  } catch {
    /* ignore */
  }
  return { key: "rs", dir: "desc" };
}

function persistSort(next: PersistedSort) {
  try {
    localStorage.setItem(SORT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

function signedClass(value: number | null | undefined) {
  if (value == null) return "text-muted-foreground";
  if (value > 0) return "text-bid";
  if (value < 0) return "text-ask";
  return "text-muted-foreground";
}

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
  const [sort, setSort] = useState<PersistedSort>(loadSort);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());
  const selected = symbol.toUpperCase();

  const board = useMemo(
    () => rankRelativeStrength(markets, { sort: sort.key, dir: sort.dir }),
    [markets, sort]
  );
  const selectedOnBoard = board.rows.some((r) => r.symbol.toUpperCase() === selected);

  useEffect(() => {
    const container = scrollerRef.current;
    const row = rowRefs.current.get(selected);
    if (!container || !row) return;
    alignRowToTop(container, row, 32);
  }, [selected, selectedOnBoard]);

  const setSortMode = (key: RsSort) => {
    const next: PersistedSort =
      sort.key === key ? { key, dir: sort.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" };
    setSort(next);
    persistSort(next);
  };

  return (
    <div ref={scrollerRef} className="min-h-0 flex-1 overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <TableRow className="h-8 hover:bg-transparent">
            {COLS.map((col) => {
              const sortKey = col.key;
              return (
              <TableHead
                key={col.label}
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
          {board.rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                No markets
              </TableCell>
            </TableRow>
          ) : (
            board.rows.map((row, i) => {
              const isSelected = row.symbol.toUpperCase() === selected;
              return (
                <TableRow
                  key={row.marketIndex}
                  ref={(el) => {
                    const key = row.symbol.toUpperCase();
                    if (el) rowRefs.current.set(key, el);
                    else rowRefs.current.delete(key);
                  }}
                  data-state={isSelected ? "selected" : undefined}
                  className="h-9 cursor-pointer tabular-nums"
                  onClick={() => onSymbolChange?.(row.symbol)}
                >
                  <TableCell className="text-right text-muted-foreground">{i + 1}</TableCell>
                  <TableCell>
                    <div className="flex min-w-0 items-center gap-2">
                      <TokenMark symbol={row.symbol} />
                      <span
                        className={cn(
                          "font-sans text-lg",
                          row.isNumeraire ? "text-muted-foreground" : "text-text"
                        )}
                      >
                        {row.symbol}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className={cn("text-right", signedClass(row.change24h))}>
                    {formatPct(row.change24h)}
                  </TableCell>
                  <TableCell className={cn("text-right", signedClass(row.relativeStrength))}>
                    {formatPct(row.relativeStrength)}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {formatUsdCompact(row.volume24h) || "—"}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {formatUsdCompact(row.openInterest) || "—"}
                  </TableCell>
                  <TableCell className={cn("text-right", fundingClass(row.fundingRate))}>
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
