import { memo, useEffect, useMemo, useRef, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type LiquidationSummaryHours, type Market } from "@/lib/api";
import { uniqueSymbolMarkets } from "@/lib/algos";
import {
  foldLiquidationWindow,
  rankLiquidationHeat,
  type LiqHeatDir,
  type LiqHeatSort,
  type LiquidationHeatInput,
} from "@/lib/liquidationHeat";
import { cn, formatUsdCompact } from "@/lib/utils";

const HOURS_KEY = "mayedge-scan-liq-hours";
const SORT_KEY = "mayedge-scan-liq-sort";
const HOURS = [1, 4, 24] as const;

type PersistedSort = { key: LiqHeatSort; dir: LiqHeatDir };

const COLS: { key: LiqHeatSort | null; label: string; align: "start" | "end" }[] = [
  { key: null, label: "Market", align: "start" },
  { key: "long", label: "Long", align: "end" },
  { key: "short", label: "Short", align: "end" },
  { key: "total", label: "Total", align: "end" },
  { key: "share", label: "vs OI", align: "end" },
  { key: "net", label: "Net", align: "end" },
  { key: null, label: "", align: "start" },
];

function loadHours(fallback: LiquidationSummaryHours): LiquidationSummaryHours {
  try {
    const n = parseInt(localStorage.getItem(HOURS_KEY) ?? "", 10);
    if (n === 1 || n === 4 || n === 24) return n;
  } catch {
    /* ignore */
  }
  return fallback;
}

function persistHours(hours: LiquidationSummaryHours) {
  try {
    localStorage.setItem(HOURS_KEY, String(hours));
  } catch {
    /* ignore */
  }
}

function loadSort(): PersistedSort {
  try {
    const raw = localStorage.getItem(SORT_KEY);
    if (!raw) return { key: "total", dir: "desc" };
    const parsed = JSON.parse(raw) as PersistedSort;
    if (
      (parsed?.key === "total" ||
        parsed?.key === "long" ||
        parsed?.key === "short" ||
        parsed?.key === "net" ||
        parsed?.key === "share") &&
      (parsed?.dir === "asc" || parsed?.dir === "desc")
    ) {
      return parsed;
    }
  } catch {
    /* ignore */
  }
  return { key: "total", dir: "desc" };
}

function persistSort(next: PersistedSort) {
  try {
    localStorage.setItem(SORT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

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
  shareOfOi,
  netUsd,
  maxTotal,
}: {
  longUsd: number;
  shortUsd: number;
  totalUsd: number;
  shareOfOi: number | null;
  netUsd: number;
  maxTotal: number;
}) {
  return (
    <>
      <TableCell className="text-right text-ask">{formatUsd(longUsd)}</TableCell>
      <TableCell className="text-right text-bid">{formatUsd(shortUsd)}</TableCell>
      <TableCell className="text-right">{formatUsd(totalUsd)}</TableCell>
      <TableCell className="text-right text-muted-foreground">{formatSharePct(shareOfOi)}</TableCell>
      <TableCell className={cn("text-right", netClass(netUsd))}>{formatNet(netUsd)}</TableCell>
      <TableCell>
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
  const [sort, setSort] = useState<PersistedSort>(loadSort);
  const [raw, setRaw] = useState<LiquidationHeatInput[]>([]);
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());
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

  useEffect(() => {
    rowRefs.current.get(selected)?.scrollIntoView({ block: "nearest" });
  }, [selected, rows]);

  const setSortMode = (key: LiqHeatSort) => {
    const next: PersistedSort =
      sort.key === key ? { key, dir: sort.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" };
    setSort(next);
    persistSort(next);
  };

  const selectHours = (next: LiquidationSummaryHours) => {
    persistHours(next);
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
            if (n === 1 || n === 4 || n === 24) selectHours(n);
          }}
        >
          {HOURS.map((h) => (
            <ToggleGroupItem
              key={h}
              value={String(h)}
              className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
            >
              {h}h
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="h-8 hover:bg-transparent">
              {COLS.map((col, i) => {
                const sortKey = col.key;
                return (
                  <TableHead
                    key={col.label || `bar-${i}`}
                    className={cn(
                      "font-mono text-[10px] tracking-wide uppercase",
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
            {fold.totalUsd > 0 ? (
              <>
                <TableRow className="h-9 bg-panel hover:bg-panel tabular-nums [&>td]:bg-panel">
                  <TableCell>
                    <div className="flex min-w-0 items-baseline gap-2">
                      <span className="font-sans text-[13px] text-text">All</span>
                      <span className="text-muted-foreground">{fold.marketCount}</span>
                    </div>
                  </TableCell>
                  <LiqMetricCells
                    longUsd={fold.longUsd}
                    shortUsd={fold.shortUsd}
                    totalUsd={fold.totalUsd}
                    shareOfOi={null}
                    netUsd={fold.shortUsd - fold.longUsd}
                    maxTotal={maxTotal}
                  />
                </TableRow>
                {topRow && fold.top ? (
                  <TableRow
                    className="h-9 cursor-pointer bg-panel tabular-nums [&>td]:bg-panel"
                    data-state={topRow.symbol.toUpperCase() === selected ? "selected" : undefined}
                    onClick={() => onSymbolChange?.(topRow.symbol)}
                  >
                    <TableCell>
                      <div className="flex min-w-0 items-center gap-2">
                        <TokenMark symbol={topRow.symbol} />
                        <span className="font-sans text-[13px] text-text">{topRow.symbol}</span>
                        <span className="text-muted-foreground">{formatWindowShare(fold.top.share)}</span>
                      </div>
                    </TableCell>
                    <LiqMetricCells
                      longUsd={topRow.longUsd}
                      shortUsd={topRow.shortUsd}
                      totalUsd={topRow.totalUsd}
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
                <TableCell colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                  No liquidations in this window
                </TableCell>
              </TableRow>
            ) : (
              listRows.map((row) => {
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
                    <TableCell>
                      <div className="flex min-w-0 items-center gap-2">
                        <TokenMark symbol={row.symbol} />
                        <span className="font-sans text-[13px] text-text">{row.symbol}</span>
                      </div>
                    </TableCell>
                    <LiqMetricCells
                      longUsd={row.longUsd}
                      shortUsd={row.shortUsd}
                      totalUsd={row.totalUsd}
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

export { loadHours as loadLiqHours };
