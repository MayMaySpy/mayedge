import { ChevronDown, Search, Star, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { uniqueSymbolMarkets } from "@/lib/algos";
import type { Market } from "@/lib/api";
import { useFavorites } from "@/lib/favorites";
import {
  filterPickerMarkets,
  formatFundingPct,
  lastPrice,
  sortPickerMarkets,
  type PickerSort,
  type PickerTab,
  type SortDir,
} from "@/lib/marketPicker";
import { useRecents } from "@/lib/recents";
import { cn, formatPct, formatPrice, formatUsdCompact } from "@/lib/utils";

const SORT_KEY = "mayedge-picker-sort";

interface MarketPickerProps {
  markets: Market[];
  symbol: string;
  onSymbolChange: (symbol: string) => void;
}

type PersistedSort = { key: PickerSort; dir: SortDir };

function loadSort(): PersistedSort {
  try {
    const raw = localStorage.getItem(SORT_KEY);
    if (!raw) return { key: "volume", dir: "desc" };
    if (raw === "change" || raw === "volume") return { key: raw, dir: "desc" };
    const parsed = JSON.parse(raw) as PersistedSort;
    if (parsed?.key && parsed?.dir) return parsed;
  } catch {
    /* ignore */
  }
  return { key: "volume", dir: "desc" };
}

function persistSort(next: PersistedSort) {
  try {
    localStorage.setItem(SORT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

function changeClass(change: number | null | undefined) {
  if (change == null) return "text-muted-foreground";
  if (change > 0) return "text-bid";
  if (change < 0) return "text-ask";
  return "text-muted-foreground";
}

function fundingClass(rate: number | null | undefined) {
  if (rate == null || rate === 0) return "text-text";
  return rate > 0 ? "text-ask" : "text-bid";
}

const COLS: { key: PickerSort; label: string; align: "start" | "end"; width: string }[] = [
  { key: "symbol", label: "Market", align: "start", width: "w-[220px]" },
  { key: "last", label: "Last", align: "end", width: "w-[88px]" },
  { key: "change", label: "24h", align: "end", width: "w-[72px]" },
  { key: "volume", label: "Volume", align: "end", width: "w-[88px]" },
  { key: "oi", label: "Open interest", align: "end", width: "w-[96px]" },
  { key: "funding", label: "Funding", align: "end", width: "w-[88px]" },
];

export const MarketPicker = memo(function MarketPicker({
  markets,
  symbol,
  onSymbolChange,
}: MarketPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<PickerTab>("all");
  const [sort, setSort] = useState<PersistedSort>(loadSort);
  const [hi, setHi] = useState(0);
  const [favorites, toggleFavorite] = useFavorites();
  const [recents, , removeRecent] = useRecents();
  const searchRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());

  const show = (next: boolean) => {
    setOpen(next);
    if (next) {
      setQuery("");
      setTab("all");
      setHi(0);
    }
  };

  const universe = useMemo(() => uniqueSymbolMarkets(markets), [markets]);
  const current = universe.find((m) => m.symbol === symbol) ?? null;
  const change = current?.change_24h;

  const rows = useMemo(() => {
    const filtered = filterPickerMarkets(universe, query, tab, favorites);
    return sortPickerMarkets(filtered, sort.key, sort.dir);
  }, [universe, query, tab, favorites, sort]);

  const recentMarkets = useMemo(() => {
    const bySym = new Map(universe.map((m) => [m.symbol, m]));
    return recents.map((s) => bySym.get(s)).filter((m): m is Market => m != null);
  }, [recents, universe]);

  const active = rows.length === 0 ? 0 : Math.min(hi, rows.length - 1);
  const activeSym = rows[active]?.symbol;

  useEffect(() => {
    if (!activeSym) return;
    rowRefs.current.get(activeSym)?.scrollIntoView({ block: "nearest" });
  }, [activeSym]);

  const pick = (sym: string) => {
    onSymbolChange(sym);
    setOpen(false);
  };

  const setSortMode = (key: PickerSort) => {
    const next: PersistedSort =
      sort.key === key
        ? { key, dir: sort.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "symbol" ? "asc" : "desc" };
    setSort(next);
    persistSort(next);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHi((i) => Math.min(rows.length - 1, i + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHi((i) => Math.max(0, i - 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const m = rows[active];
      if (m) pick(m.symbol);
      return;
    }
    const typing = (e.target as HTMLElement).tagName === "INPUT";
    if ((e.key === "f" || e.key === "F") && (!typing || !query)) {
      e.preventDefault();
      const m = rows[active];
      if (m) toggleFavorite(m.symbol);
    }
  };

  return (
    <Popover open={open} onOpenChange={show}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 justify-start gap-1.5 px-1.5 font-normal"
        >
          <span className="flex items-center gap-2 text-left">
            <TokenMark symbol={symbol} className="size-4" />
            <span className="font-sans text-lg font-medium tracking-tight">{symbol}</span>
            <span className={cn("font-mono text-lg", changeClass(change))}>
              {formatPct(change)}
            </span>
          </span>
          <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={4}
        onKeyDown={onKeyDown}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          searchRef.current?.focus();
        }}
        className="flex h-[min(70vh,560px)] w-[min(calc(100vw-1.5rem),720px)] flex-col overflow-hidden p-0"
      >

          <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
            <Search className="size-3.5 shrink-0 text-muted-foreground" />
            <Input
              ref={searchRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setHi(0);
              }}
              placeholder="Search markets"
              aria-label="Search markets"
              autoComplete="off"
              spellCheck={false}
              className="h-full border-0 bg-transparent px-0 font-sans shadow-none focus-visible:ring-0"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Close"
              className="size-7"
              onClick={() => show(false)}
            >
              <X />
            </Button>
          </div>

          {recentMarkets.length > 0 && (
            <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-rule px-3 py-2">
              <span className="mr-0.5 shrink-0 font-mono text-xs tracking-wide text-muted-foreground uppercase">
                Recents
              </span>
              {recentMarkets.map((m) => (
                <div
                  key={m.symbol}
                  className="inline-flex h-7 shrink-0 items-center overflow-hidden rounded-full bg-elevated"
                >
                  <button
                    type="button"
                    onClick={() => pick(m.symbol)}
                    className="inline-flex h-full items-center gap-1.5 pr-1 pl-1.5 text-base text-text"
                  >
                    <TokenMark symbol={m.symbol} className="size-3.5" />
                    {m.symbol}
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${m.symbol} from recent`}
                    onClick={() => removeRecent(m.symbol)}
                    className="inline-flex h-full items-center pr-1.5 pl-0.5 text-muted-foreground hover:text-text"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-2">
            <ToggleGroup
              type="single"
              variant="seg"
              size="sm"
              spacing={0}
              value={tab}
              onValueChange={(v) => {
                if (v === "all" || v === "favorites") {
                  setTab(v);
                  setHi(0);
                }
              }}
            >
              <ToggleGroupItem value="all">All</ToggleGroupItem>
              <ToggleGroupItem value="favorites">Favorites</ToggleGroupItem>
            </ToggleGroup>
            <span className="pr-1 font-mono text-sm text-muted-foreground tabular-nums">
              {rows.length} market{rows.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse text-base">
              <thead className="sticky top-0 z-10 bg-panel">
                <tr className="h-8 border-b border-rule">
                  {COLS.map((col) => (
                    <th
                      key={col.key}
                      className={cn(
                        "px-2 font-mono text-xs font-normal tracking-wide text-muted-foreground uppercase",
                        col.width,
                        col.align === "end" ? "text-right" : "text-left"
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => setSortMode(col.key)}
                        className={cn(
                          "inline-flex items-center gap-0.5 uppercase hover:text-text",
                          col.align === "end" && "ml-auto",
                          sort.key === col.key && "text-text"
                        )}
                      >
                        {col.label}
                        {sort.key === col.key ? (sort.dir === "desc" ? " ↓" : " ↑") : null}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-base text-muted-foreground">
                      {tab === "favorites" && !query
                        ? "Star a market to pin it here"
                        : "No markets match"}
                    </td>
                  </tr>
                ) : (
                  rows.map((m, i) => {
                    const fav = favorites.includes(m.symbol);
                    const last = lastPrice(m);
                    const selected = m.symbol === symbol;
                    const activeRow = i === active;
                    return (
                      <tr
                        key={m.market_index}
                        ref={(el) => {
                          if (el) rowRefs.current.set(m.symbol, el);
                          else rowRefs.current.delete(m.symbol);
                        }}
                        onMouseEnter={() => setHi(i)}
                        onClick={() => pick(m.symbol)}
                        className={cn(
                          "h-9 cursor-pointer border-b border-rule/70 tabular-nums",
                          activeRow && "bg-elevated/40",
                          selected && !activeRow && "bg-elevated/20"
                        )}
                      >
                        <td className="px-2">
                          <div className="flex min-w-0 items-center gap-2">
                            <button
                              type="button"
                              aria-label={fav ? `Unpin ${m.symbol}` : `Pin ${m.symbol}`}
                              className={cn(
                                "inline-flex size-6 shrink-0 items-center justify-center rounded-full",
                                fav ? "text-warn" : "text-muted-foreground hover:text-text"
                              )}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                toggleFavorite(m.symbol);
                              }}
                            >
                              <Star className={cn("size-3.5", fav && "fill-warn")} />
                            </button>
                            <TokenMark symbol={m.symbol} />
                            <span className="font-sans text-lg text-text">{m.symbol}</span>
                            {m.max_leverage ? (
                              <span className="text-base text-muted-foreground tabular-nums">
                                {m.max_leverage}x
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-2 text-right font-mono text-base text-text">
                          {last > 0 ? formatPrice(last, m.price_decimals ?? 4) : "—"}
                        </td>
                        <td
                          className={cn(
                            "px-2 text-right font-mono text-base",
                            changeClass(m.change_24h)
                          )}
                        >
                          {formatPct(m.change_24h)}
                        </td>
                        <td className="px-2 text-right font-mono text-base text-muted-foreground">
                          {formatUsdCompact(m.volume_24h) || "—"}
                        </td>
                        <td className="px-2 text-right font-mono text-base text-muted-foreground">
                          {formatUsdCompact(m.open_interest) || "—"}
                        </td>
                        <td
                          className={cn(
                            "px-2 text-right font-mono text-base",
                            fundingClass(m.funding_rate)
                          )}
                        >
                          {formatFundingPct(m.funding_rate)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          <div className="flex h-9 shrink-0 items-center gap-4 border-t border-border px-3 text-sm text-muted-foreground">
            <KbdGroup>
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd>
              <span>Navigate</span>
            </KbdGroup>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>↵</Kbd>
              Select
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>F</Kbd>
              Favorite
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>Esc</Kbd>
              Close
            </span>
          </div>
      </PopoverContent>
    </Popover>
  );
});
