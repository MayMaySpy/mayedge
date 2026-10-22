import { memo, useEffect, useMemo, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import { SortableHeads } from "@/components/widgets/SortableHeads";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableName,
  TableRow,
} from "@/components/ui/table";
import { api, type LiquidationSummaryHours, type Market } from "@/lib/api";
import { uniqueSymbolMarkets } from "@/lib/algos";
import { LIQ_HOURS, persistLiqHours } from "@/lib/liqHours";
import {
  foldLiquidationWindow,
  rankLiquidationHeat,
  type LiqHeatSort,
  type LiquidationHeatInput,
} from "@/lib/liquidationHeat";
import { useSelectedRowInView } from "@/lib/scanScroll";
import { useStoredSort, type SortCol } from "@/lib/tableSort";
import { cn, formatUsdCompact } from "@/lib/utils";

const SORT_KEY = "mayedge-scan-liq-sort";

const SORTS: readonly LiqHeatSort[] = ["total", "long", "short", "net", "share", "largest"];

const COLS: readonly SortCol<LiqHeatSort>[] = [
  { key: null, label: "Market", align: "start" },
  { key: "long", label: "Long", align: "end", hideBelow: "sm" },
  { key: "short", label: "Short", align: "end", hideBelow: "sm" },
  { key: "total", label: "Total", align: "end" },
  { key: null, label: "Share", align: "end", hideBelow: "lg" },
  { key: "largest", label: "Largest", align: "end", hideBelow: "md" },
  { key: "share", label: "vs OI", align: "end", hideBelow: "md" },
  { key: "net", label: "Net", align: "end" },
  { key: null, label: "", align: "start", hideBelow: "lg" },
];

function formatUsd(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "$0";
  return formatUsdCompact(Math.abs(n)) || "$0";
}

function formatSharePct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const pct = n * 100;
  if (pct >= 10) return `${pct.toFixed(0)}%`;
  if (pct >= 1) return `${pct.toFixed(1)}%`;
  return `${pct.toFixed(2)}%`;
}

function formatNet(n: number): string {
  const core = formatUsd(Math.abs(n));
  if (n > 0) return `+${core}`;
  if (n < 0) return `-${core}`;
  return core;
}

function netClass(n: number) {
  if (n > 0) return "text-bid";
  if (n < 0) return "text-ask";
  return "text-muted-foreground";
}

function formatWindowShare(share: number): string {
  const pct = share * 100;
  if (pct >= 1) return `${Math.round(pct)}%`;
  return `${pct.toFixed(1)}%`;
}

function HeatBar({
  longUsd,
  shortUsd,
  totalUsd,
  maxTotal,
}: {
  longUsd: number;
  shortUsd: number;
  totalUsd: number;
  maxTotal: number;
}) {
  const width = maxTotal > 0 ? (totalUsd / maxTotal) * 100 : 0;
  const shortShare = totalUsd > 0 ? (shortUsd / totalUsd) * 100 : 0;
  const longShare = totalUsd > 0 ? (longUsd / totalUsd) * 100 : 0;
  return (
    <div className="flex h-1.5 w-full min-w-16 items-center">
      <div className="flex h-1.5 overflow-hidden rounded-sm bg-elevated" style={{ width: `${width}%` }}>
        <div className="h-full bg-bid" style={{ width: `${shortShare}%` }} />
        <div className="h-full bg-ask" style={{ width: `${longShare}%` }} />
      </div>
    </div>
  );
}

function LiqMetricCells({
  longUsd,
  shortUsd,
  totalUsd,
  windowShare,
  largestUsd,
  shareOfOi,
  netUsd,
  maxTotal,
}: {
  longUsd: number;
  shortUsd: number;
  totalUsd: number;
  windowShare: number | null;
  largestUsd: number;
  shareOfOi: number | null;
  netUsd: number;
  maxTotal: number;
}) {
  return (
    <>
      <TableCell hideBelow="sm" className="text-right text-ask">{formatUsd(longUsd)}</TableCell>
      <TableCell hideBelow="sm" className="text-right text-bid">{formatUsd(shortUsd)}</TableCell>
      <TableCell className="text-right">{formatUsd(totalUsd)}</TableCell>
      <TableCell hideBelow="lg" className="text-right text-muted-foreground">{formatSharePct(windowShare)}</TableCell>
      <TableCell hideBelow="md" className="text-right">{formatUsd(largestUsd)}</TableCell>
      <TableCell hideBelow="md" className="text-right text-muted-foreground">{formatSharePct(shareOfOi)}</TableCell>
      <TableCell className={cn("text-right", netClass(netUsd))}>{formatNet(netUsd)}</TableCell>
      <TableCell hideBelow="lg">
        <HeatBar longUsd={longUsd} shortUsd={shortUsd} totalUsd={totalUsd} maxTotal={maxTotal} />
      </TableCell>
    </>
  );
}

interface LiquidationHeatTableProps {
  hours: LiquidationSummaryHours;
  onHoursChange: (hours: LiquidationSummaryHours) => void;
  markets: readonly Market[];
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const LiquidationHeatTable = memo(function LiquidationHeatTable({
  hours,
  onHoursChange,
  markets,
  symbol,
  onSymbolChange,
}: LiquidationHeatTableProps) {
  const [sort, setSortMode] = useStoredSort(SORT_KEY, SORTS, "total");
  const [raw, setRaw] = useState<LiquidationHeatInput[]>([]);
  const selected = symbol.toUpperCase();

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api
        .liquidationSummary(hours)
        .then((data) => {
          if (!cancelled) setRaw(data.rows);
        })
        .catch(() => {
          if (!cancelled) setRaw([]);
        });
    };
    load();
    const id = setInterval(load, 20_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [hours]);

  const openInterest = useMemo(() => {
    const out: Record<string, number> = {};
    for (const m of uniqueSymbolMarkets([...markets])) {
      const oi = m.open_interest;
      if (oi != null && oi > 0) out[m.symbol.toUpperCase()] = oi;
    }
    return out;
  }, [markets]);

  const rows = useMemo(
    () => rankLiquidationHeat(raw, { sort: sort.key, dir: sort.dir, openInterest }),
    [raw, sort, openInterest]
  );

  const fold = useMemo(() => foldLiquidationWindow(rows), [rows]);
  const topRow = useMemo(
    () => (fold.top ? rows.find((r) => r.symbol === fold.top?.symbol) : undefined),
    [fold.top, rows]
  );
  const listRows = useMemo(
    () => (topRow ? rows.filter((r) => r.symbol !== topRow.symbol) : rows),
    [rows, topRow]
  );
  const maxTotal = fold.totalUsd;

  const { scrollerRef, rowRef } = useSelectedRowInView(
    selected,
    rows.some((r) => r.symbol.toUpperCase() === selected)
  );

  const selectHours = (next: LiquidationSummaryHours) => {
    persistLiqHours(next);
    onHoursChange(next);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-7 shrink-0 items-center border-b border-border px-2">
        <ToggleGroup
          type="single"
          size="sm"
          spacing={0}
          value={String(hours)}
          onValueChange={(v) => {
            const n = parseInt(v, 10);
            if (LIQ_HOURS.some((h) => h.value === n)) selectHours(n as LiquidationSummaryHours);
          }}
        >
          {LIQ_HOURS.map((h) => (
            <ToggleGroupItem
              key={h.value}
              value={String(h.value)}
              className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
            >
              {h.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <div ref={scrollerRef} className="min-h-0 flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="hover:bg-transparent">
              <SortableHeads cols={COLS} sort={sort} onSort={setSortMode} />
            </TableRow>
            {fold.totalUsd > 0 ? (
              <>
                <TableRow className="bg-panel hover:bg-panel [&>td]:bg-panel">
                  <TableCell>
                    <div className="flex min-w-0 items-baseline gap-2">
                      <TableName className="text-text">All</TableName>
                      <span className="text-muted-foreground">{fold.marketCount}</span>
                    </div>
                  </TableCell>
                  <LiqMetricCells
                    longUsd={fold.longUsd}
                    shortUsd={fold.shortUsd}
                    totalUsd={fold.totalUsd}
                    windowShare={1}
                    largestUsd={fold.largestUsd}
                    shareOfOi={null}
                    netUsd={fold.shortUsd - fold.longUsd}
                    maxTotal={maxTotal}
                  />
                </TableRow>
                {topRow && fold.top ? (
                  <TableRow
                    className="cursor-pointer bg-panel [&>td]:bg-panel"
                    data-state={topRow.symbol.toUpperCase() === selected ? "selected" : undefined}
                    onClick={() => onSymbolChange?.(topRow.symbol)}
                  >
                    <TableCell>
                      <div className="flex min-w-0 items-center gap-2">
                        <TokenMark symbol={topRow.symbol} className="size-4" />
                        <TableName className="text-text">{topRow.symbol}</TableName>
                        <span className="text-muted-foreground">{formatWindowShare(fold.top.share)}</span>
                      </div>
                    </TableCell>
                    <LiqMetricCells
                      longUsd={topRow.longUsd}
                      shortUsd={topRow.shortUsd}
                      totalUsd={topRow.totalUsd}
                      windowShare={topRow.windowShare}
                      largestUsd={topRow.largestUsd}
                      shareOfOi={topRow.shareOfOi}
                      netUsd={topRow.netUsd}
                      maxTotal={maxTotal}
                    />
                  </TableRow>
                ) : null}
              </>
            ) : null}
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                  No liquidations in this window
                </TableCell>
              </TableRow>
            ) : (
              listRows.map((row) => {
                const isSelected = row.symbol.toUpperCase() === selected;
                return (
                  <TableRow
                    key={row.marketIndex}
                    ref={rowRef(row.symbol)}
                    data-state={isSelected ? "selected" : undefined}
                    className="cursor-pointer"
                    onClick={() => onSymbolChange?.(row.symbol)}
                  >
                    <TableCell>
                      <div className="flex min-w-0 items-center gap-2">
                        <TokenMark symbol={row.symbol} className="size-4" />
                        <TableName className="text-text">{row.symbol}</TableName>
                      </div>
                    </TableCell>
                    <LiqMetricCells
                      longUsd={row.longUsd}
                      shortUsd={row.shortUsd}
                      totalUsd={row.totalUsd}
                      windowShare={row.windowShare}
                      largestUsd={row.largestUsd}
                      shareOfOi={row.shareOfOi}
                      netUsd={row.netUsd}
                      maxTotal={maxTotal}
                    />
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
});
