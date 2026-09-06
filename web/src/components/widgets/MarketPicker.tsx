import { Star } from "lucide-react";
import { memo, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@/components/ui/combobox";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Market } from "@/lib/api";
import { uniqueSymbolMarkets } from "@/lib/algos";
import { useFavorites } from "@/lib/favorites";
import { cn, formatPct, formatUsdCompact } from "@/lib/utils";

const SORT_KEY = "mayedge-picker-sort";
type SortMode = "volume" | "change";

interface MarketPickerProps {
  markets: Market[];
  symbol: string;
  onSymbolChange: (symbol: string) => void;
}

function loadSort(): SortMode {
  try {
    const raw = localStorage.getItem(SORT_KEY);
    if (raw === "change" || raw === "volume") return raw;
  } catch {
    /* ignore */
  }
  return "volume";
}

function changeClass(change: number | null | undefined) {
  if (change == null) return "text-muted";
  if (change > 0) return "text-bid";
  if (change < 0) return "text-ask";
  return "text-muted";
}

export const MarketPicker = memo(function MarketPicker({ markets, symbol, onSymbolChange }: MarketPickerProps) {
  const [sort, setSort] = useState<SortMode>(loadSort);
  const [favorites, toggleFavorite] = useFavorites();

  const current = uniqueSymbolMarkets(markets).find((m) => m.symbol === symbol) ?? null;
  const change = current?.change_24h;

  const sorted = useMemo(() => {
    const favSet = new Set(favorites);
    return uniqueSymbolMarkets(markets).sort((a, b) => {
      const af = favSet.has(a.symbol) ? 1 : 0;
      const bf = favSet.has(b.symbol) ? 1 : 0;
      if (af !== bf) return bf - af;
      if (sort === "change") {
        return (b.change_24h ?? -Infinity) - (a.change_24h ?? -Infinity);
      }
      return (b.volume_24h ?? 0) - (a.volume_24h ?? 0) || a.symbol.localeCompare(b.symbol);
    });
  }, [markets, favorites, sort]);

  const setSortMode = (next: SortMode) => {
    setSort(next);
    try {
      localStorage.setItem(SORT_KEY, next);
    } catch {
      /* ignore */
    }
  };

  return (
    <Combobox
      items={sorted}
      value={current}
      onValueChange={(market) => {
        if (market) onSymbolChange(market.symbol);
      }}
      itemToStringValue={(market) => market.symbol}
    >
      <ComboboxTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            className="h-7 justify-start gap-2 px-1.5 font-normal"
          />
        }
      >
        <span className="flex items-center gap-2 text-left">
          <span className="font-mono text-sm font-medium tracking-tight">{symbol}</span>
          <span className={cn("font-mono text-[11px]", changeClass(change))}>
            {formatPct(change)}
          </span>
        </span>
      </ComboboxTrigger>
      <ComboboxContent className="w-80 min-w-80">
        <div className="flex items-center gap-1 pr-1">
          <ComboboxInput
            showTrigger={false}
            placeholder="Search markets"
            className="min-w-0 flex-1 font-mono text-xs"
          />
          <ToggleGroup
            type="single"
            variant="seg"
            size="sm"
            spacing={0}
            value={sort}
            onValueChange={(v) => {
              if (v === "volume" || v === "change") setSortMode(v);
            }}
            className="shrink-0"
          >
            <ToggleGroupItem value="volume">Vol</ToggleGroupItem>
            <ToggleGroupItem value="change">24h</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <ComboboxEmpty>No markets match</ComboboxEmpty>
        <ComboboxList>
          {(m) => {
            const fav = favorites.includes(m.symbol);
            const vol = formatUsdCompact(m.volume_24h);
            return (
              <ComboboxItem key={m.market_index} value={m} className="font-mono text-xs">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-5 shrink-0"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleFavorite(m.symbol);
                      }}
                      onPointerDown={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                      }}
                    >
                      <Star className={cn(fav && "fill-bid text-bid")} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{fav ? "Unpin" : "Pin to top"}</TooltipContent>
                </Tooltip>
                <span className="font-medium">{m.symbol}</span>
                <span className="ml-auto text-[10px] text-muted">{vol || "—"}</span>
                <span className={cn("w-14 text-right text-[10px]", changeClass(m.change_24h))}>
                  {formatPct(m.change_24h)}
                </span>
              </ComboboxItem>
            );
          }}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
});
