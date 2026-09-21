import {
  createChart,
  LineSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { Check, ChevronDown, Plus, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TokenMark } from "@/components/desk/TokenMark";
import { uniqueSymbolMarkets } from "@/lib/algos";
import type { Market } from "@/lib/api";
import { overlayQuote, useLiveQuotes } from "@/lib/liveData";
import { sortPickerMarkets, type SortDir } from "@/lib/marketPicker";
import { theme } from "@/lib/theme";
import { cn, formatPct, formatUsdCompact } from "@/lib/utils";
import {
  WATCH_SET_MAX,
  addToWatchSet,
  assignWatchPane,
  createWatchSet,
  deleteWatchSet,
  removeFromWatchSet,
  renameWatchSet,
  samplingSymbols,
  setWatchLabels,
  setWatchLayout,
  useWatchDesk,
  type WatchLayout,
  type WatchSet,
} from "@/lib/watchSets";
import { listWatchChips, type WatchChip } from "@/lib/watchChips";
import { lastForWatch, pathFromSamples, watchLineColor, type PathPoint } from "@/lib/watchPath";
import { getWatchSamples, rollWatch } from "@/lib/watchSamples";

interface WatchBoardProps {
  windowSec: number;
  markets: readonly Market[];
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

function pctAt(path: PathPoint[], t: number | null): number | null {
  if (!path.length) return null;
  if (t == null) return path[path.length - 1]?.pct ?? null;
  for (let i = path.length - 1; i >= 0; i--) {
    if (path[i].t <= t) return path[i].pct;
  }
  return null;
}

function paneEdge(layout: WatchLayout, index: number): string {
  if (layout === 2) return index === 0 ? "border-b border-border" : "";
  if (layout === 4) {
    return cn(
      (index === 0 || index === 2) && "border-r border-border",
      (index === 0 || index === 1) && "border-b border-border"
    );
  }
  return "";
}

const EMPTY_WATCH: readonly string[] = [];

function WatchChipButton({
  chip,
  selected,
  onFocus,
  onRemove,
}: {
  chip: WatchChip;
  selected: boolean;
  onFocus: () => void;
  onRemove: () => void;
}) {
  const tone =
    chip.pct == null
      ? "text-muted-foreground"
      : chip.pct > 0
        ? "text-bid"
        : chip.pct < 0
          ? "text-ask"
          : "text-muted-foreground";
  return (
    <div
      className={cn(
        "flex h-6 shrink-0 items-center gap-1 rounded-md border px-1.5 font-mono text-sm",
        selected ? "border-foreground/40 bg-elevated/20" : "border-border"
      )}
    >
      <button type="button" className="flex items-center gap-1" onClick={onFocus}>
        <span className="size-1.5 shrink-0 rounded-full" style={{ background: chip.color }} />
        <span>{chip.symbol}</span>
        <span className={cn("tabular-nums", tone)}>{formatPct(chip.pct)}</span>
      </button>
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground"
        title={`Remove ${chip.symbol}`}
        onClick={onRemove}
      >
        <X className="size-3" />
      </button>
    </div>
  );
}

const WatchAddPicker = memo(function WatchAddPicker({
  markets,
  listed,
  onAdd,
}: {
  markets: readonly Market[];
  listed: ReadonlySet<string>;
  onAdd: (symbol: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dir, setDir] = useState<SortDir>("desc");
  const rows = useMemo(() => {
    const q = query.trim().toUpperCase();
    const filtered = uniqueSymbolMarkets([...markets]).filter((m) => {
      if (listed.has(m.symbol)) return false;
      if (!q) return true;
      return m.symbol.toUpperCase().includes(q);
    });
    return sortPickerMarkets(filtered, "volume", dir);
  }, [markets, listed, query, dir]);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-6 shrink-0 px-1.5 font-mono text-sm"
          title="Add Markets to Watch"
        >
          <Plus className="size-3" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-72 flex-col gap-2 p-2">
        <Input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search markets"
          className="h-7 text-base"
        />
        <button
          type="button"
          className="flex items-center justify-between px-1 font-mono text-xs text-muted-foreground hover:text-foreground"
          title="Sort by volume"
          onClick={() => setDir((d) => (d === "desc" ? "asc" : "desc"))}
        >
          <span>Volume</span>
          <span>{dir === "desc" ? "↓" : "↑"}</span>
        </button>
        <div className="max-h-56 overflow-auto">
          {rows.length === 0 ? (
            <p className="px-1 py-4 text-center text-base text-muted-foreground">
              No markets match
            </p>
          ) : (
            rows.map((m) => (
              <button
                key={m.market_index}
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left font-mono text-base hover:bg-accent"
                onClick={() => {
                  onAdd(m.symbol);
                  setQuery("");
                  setOpen(false);
                }}
              >
                <TokenMark symbol={m.symbol} className="size-4" />
                <span className="min-w-0 flex-1 truncate">{m.symbol}</span>
                <span className="text-sm text-muted-foreground tabular-nums">
                  {formatUsdCompact(m.volume_24h) || "—"}
                </span>
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
});

function WatchSetMenu({
  sets,
  currentId,
  paneIndex,
  onRename,
}: {
  sets: readonly WatchSet[];
  currentId: string | null;
  paneIndex: number;
  onRename: () => void;
}) {
  const current = sets.find((s) => s.id === currentId);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 max-w-40 shrink-0 gap-1 px-1.5 font-mono text-sm font-medium text-foreground"
          title="Watch Set"
        >
          <span className="truncate">{current?.name ?? "Set"}</span>
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-44">
        {sets.map((s) => (
          <DropdownMenuItem key={s.id} onClick={() => assignWatchPane(paneIndex, s.id)}>
            <Check className={cn("size-3", s.id === currentId ? "opacity-100" : "opacity-0")} />
            <span className="truncate">{s.name}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={sets.length >= WATCH_SET_MAX}
          onClick={() => {
            const id = createWatchSet();
            if (id) assignWatchPane(paneIndex, id);
          }}
        >
          New set
        </DropdownMenuItem>
        {current ? (
          <>
            <DropdownMenuItem onClick={onRename}>Rename</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={() => deleteWatchSet(current.id)}>
              Delete
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const WatchPane = memo(function WatchPane({
  index,
  layout,
  watchSet,
  sets,
  windowSec,
  markets,
  labels,
  symbol,
  now,
  onSymbolChange,
}: {
  index: number;
  layout: WatchLayout;
  watchSet: WatchSet | null;
  sets: readonly WatchSet[];
  windowSec: number;
  markets: readonly Market[];
  labels: boolean;
  symbol: string;
  now: number;
  onSymbolChange?: (symbol: string) => void;
}) {
  const [hoverT, setHoverT] = useState<number | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const onSymbolRef = useRef(onSymbolChange);
  const watchlist = watchSet?.symbols ?? EMPTY_WATCH;
  const hasWatchlist = watchlist.length > 0;

  useEffect(() => {
    onSymbolRef.current = onSymbolChange;
  }, [onSymbolChange]);

  const t0 = now - windowSec;
  const paths = useMemo(() => {
    const out = new Map<string, PathPoint[]>();
    for (const s of watchlist) out.set(s, pathFromSamples(getWatchSamples(s), t0));
    return out;
  }, [watchlist, t0]);

  const chips = useMemo(() => {
    const pct: Record<string, number | null> = {};
    for (const s of watchlist) pct[s] = pctAt(paths.get(s) ?? [], hoverT);
    return listWatchChips(watchlist, pct);
  }, [watchlist, paths, hoverT]);
  const listed = useMemo(() => new Set(watchlist), [watchlist]);

  useEffect(() => {
    if (!hasWatchlist) return;
    if (!wrapRef.current) return;
    const wrap = wrapRef.current;
    const chart = createChart(wrap, {
      width: wrap.clientWidth,
      height: wrap.clientHeight,
      layout: {
        background: { color: theme.panel },
        textColor: theme.muted,
        fontFamily: theme.fontMono,
        fontSize: theme.chartFontSize,
      },
      grid: {
        vertLines: { color: theme.rule },
        horzLines: { color: theme.rule },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: theme.rule,
      },
      timeScale: {
        borderColor: theme.rule,
        timeVisible: true,
        secondsVisible: windowSec <= 900,
        rightOffset: 4,
        shiftVisibleRangeOnNewBar: true,
      },
    });
    chartRef.current = chart;

    const onMove = (param: { time?: unknown }) => {
      const t = typeof param.time === "number" ? param.time : null;
      setHoverT(t);
    };
    chart.subscribeCrosshairMove(onMove);

    const onClick = (param: { hoveredSeries?: ISeriesApi<"Line"> | unknown }) => {
      const hovered = param.hoveredSeries;
      if (!hovered) return;
      for (const [sym, series] of seriesRef.current) {
        if (series === hovered) {
          onSymbolRef.current?.(sym);
          return;
        }
      }
    };
    chart.subscribeClick(onClick);

    let lastW = wrap.clientWidth;
    let lastH = wrap.clientHeight;
    const ro = new ResizeObserver(() => {
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      if (w < 1 || h < 1 || (w === lastW && h === lastH)) return;
      lastW = w;
      lastH = h;
      chart.applyOptions({ width: w, height: h });
    });
    ro.observe(wrap);
    const seriesMap = seriesRef.current;

    return () => {
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      chart.remove();
      chartRef.current = null;
      seriesMap.clear();
    };
  }, [windowSec, hasWatchlist]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const keep = new Set(watchlist);
    for (const [sym, series] of seriesRef.current) {
      if (keep.has(sym)) continue;
      chart.removeSeries(series);
      seriesRef.current.delete(sym);
    }
    for (const s of watchlist) {
      if (seriesRef.current.has(s)) continue;
      const series = chart.addSeries(LineSeries, {
        color: watchLineColor(s, watchlist),
        lineWidth: 2,
        title: s,
        priceLineVisible: false,
        lastValueVisible: labels,
        crosshairMarkerVisible: true,
        priceFormat: {
          type: "custom",
          minMove: 0.01,
          formatter: (price: number) => {
            const sign = price > 0 ? "+" : "";
            return `${sign}${price.toFixed(2)}%`;
          },
        },
      });
      seriesRef.current.set(s, series);
    }
    for (const s of watchlist) {
      const series = seriesRef.current.get(s);
      const path = paths.get(s) ?? [];
      if (!series) continue;
      series.applyOptions({
        color: watchLineColor(s, watchlist),
        lastValueVisible: labels,
        title: s,
      });
      series.setData(path.map((p) => ({ time: p.t as UTCTimestamp, value: p.pct })));
    }
  }, [watchlist, paths, labels]);

  const commitRename = () => {
    if (watchSet) renameWatchSet(watchSet.id, draft);
    setRenaming(false);
  };

  const addPicker = watchSet ? (
    <WatchAddPicker markets={markets} listed={listed} onAdd={(s) => addToWatchSet(watchSet.id, s)} />
  ) : null;

  const header = (
    <div className="flex h-7 shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-1.5">
      {renaming && watchSet ? (
        <Input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") setRenaming(false);
          }}
          className="h-6 w-28 text-sm"
        />
      ) : (
        <WatchSetMenu
          sets={sets}
          currentId={watchSet?.id ?? null}
          paneIndex={index}
          onRename={() => {
            setDraft(watchSet?.name ?? "");
            setRenaming(true);
          }}
        />
      )}
      {chips.map((chip) => (
        <WatchChipButton
          key={chip.symbol}
          chip={chip}
          selected={chip.symbol === symbol}
          onFocus={() => onSymbolChange?.(chip.symbol)}
          onRemove={() => watchSet && removeFromWatchSet(watchSet.id, chip.symbol)}
        />
      ))}
      {hasWatchlist ? addPicker : null}
    </div>
  );

  return (
    <div className={cn("flex min-h-0 min-w-0 flex-col", paneEdge(layout, index))}>
      {header}
      {!watchSet ? (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>Choose a Watch Set</EmptyTitle>
            <EmptyDescription>New set, or assign one you already saved.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-6 font-mono text-sm"
              disabled={sets.length >= WATCH_SET_MAX}
              onClick={() => {
                const id = createWatchSet();
                if (id) assignWatchPane(index, id);
              }}
            >
              New set
            </Button>
          </EmptyContent>
        </Empty>
      ) : !hasWatchlist ? (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>Add Markets to Watch</EmptyTitle>
            <EmptyDescription>Plot live Paths for up to 8 Markets.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>{addPicker}</EmptyContent>
        </Empty>
      ) : (
        <div ref={wrapRef} className="min-h-0 min-w-0 flex-1" />
      )}
    </div>
  );
});

export const WatchBoard = memo(function WatchBoard({
  windowSec,
  markets,
  symbol,
  onSymbolChange,
}: WatchBoardProps) {
  const desk = useWatchDesk();
  const quotes = useLiveQuotes();
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const lastsRef = useRef<Record<string, number | null>>({});
  const deskRef = useRef(desk);

  const quoted = useMemo(
    () => uniqueSymbolMarkets([...markets]).map((m) => overlayQuote(m, quotes[m.market_index])),
    [markets, quotes]
  );

  const bySymbol = useMemo(() => {
    const map = new Map<string, Market>();
    for (const m of quoted) map.set(m.symbol, m);
    return map;
  }, [quoted]);

  const sampleSyms = useMemo(() => samplingSymbols(desk), [desk]);

  const lasts = useMemo(() => {
    const out: Record<string, number | null> = {};
    for (const s of sampleSyms) {
      const m = bySymbol.get(s);
      out[s] = m ? lastForWatch(m) : null;
    }
    return out;
  }, [sampleSyms, bySymbol]);

  useEffect(() => {
    lastsRef.current = lasts;
  }, [lasts]);

  useEffect(() => {
    deskRef.current = desk;
  }, [desk]);

  useEffect(() => {
    rollWatch(sampleSyms, lasts, Math.floor(Date.now() / 1000));
  }, [sampleSyms, lasts]);

  useEffect(() => {
    const id = window.setInterval(() => {
      const t = Math.floor(Date.now() / 1000);
      rollWatch(samplingSymbols(deskRef.current), lastsRef.current, t);
      setNow(t);
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  const panes = desk.panes.slice(0, desk.layout);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-7 shrink-0 items-center border-b border-border px-1">
        <ToggleGroup
          type="single"
          size="sm"
          spacing={0}
          value={String(desk.layout)}
          onValueChange={(v) => {
            if (v === "1" || v === "2" || v === "4") setWatchLayout(Number(v) as WatchLayout);
          }}
        >
          {(["1", "2", "4"] as const).map((n) => (
            <ToggleGroupItem
              key={n}
              value={n}
              title={n === "1" ? "One pane" : n === "2" ? "Two panes" : "Four panes"}
              className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
            >
              {n}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <div className="flex-1" />
        <Toggle
          variant="seg"
          size="sm"
          pressed={desk.labels}
          title="Show Markets on the right"
          className="h-6 px-1.5 font-mono text-sm"
          onPressedChange={(on) => setWatchLabels(on)}
        >
          Names
        </Toggle>
      </div>
      <div
        className={cn(
          "grid min-h-0 flex-1",
          desk.layout === 1 && "grid-cols-1 grid-rows-1",
          desk.layout === 2 && "grid-cols-1 grid-rows-2",
          desk.layout === 4 && "grid-cols-2 grid-rows-2"
        )}
      >
        {panes.map((_, i) => {
          const id = desk.panes[i];
          const watchSet = id ? (desk.sets.find((s) => s.id === id) ?? null) : null;
          return (
            <WatchPane
              key={i}
              index={i}
              layout={desk.layout}
              watchSet={watchSet}
              sets={desk.sets}
              windowSec={windowSec}
              markets={quoted}
              labels={desk.labels}
              symbol={symbol}
              now={now}
              onSymbolChange={onSymbolChange}
            />
          );
        })}
      </div>
    </div>
  );
});
