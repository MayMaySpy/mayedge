import { GripVertical } from "lucide-react";
import { memo, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Market } from "@/lib/api";
import { useFavorites } from "@/lib/favorites";
import { cn, formatPct, formatUsdCompact } from "@/lib/utils";

interface FavoritesBarProps {
  markets: Market[];
  symbol: string;
  onSymbolChange: (symbol: string) => void;
}

function changeVariant(change: number | null | undefined): "bid" | "ask" | "muted" {
  if (change == null || change === 0) return "muted";
  return change > 0 ? "bid" : "ask";
}

export const FavoritesBar = memo(function FavoritesBar({ markets, symbol, onSymbolChange }: FavoritesBarProps) {
  const [favorites, , reorder] = useFavorites();
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const didDrag = useRef(false);

  const items = useMemo(() => {
    const bySym = new Map(markets.map((m) => [m.symbol, m]));
    // Preserve pin order — favorites array is the source of truth.
    return favorites.map((sym) => bySym.get(sym) ?? ({ symbol: sym } as Market));
  }, [favorites, markets]);

  if (items.length === 0) return null;

  const move = (fromSym: string, toSym: string) => {
    const from = favorites.indexOf(fromSym);
    const to = favorites.indexOf(toSym);
    if (from < 0 || to < 0 || from === to) return;
    reorder(from, to);
  };

  return (
    <div className="shrink-0 border-b border-rule bg-panel">
      <ScrollArea className="h-8 w-full">
        <ToggleGroup
          type="single"
          variant="seg"
          size="sm"
          spacing={0}
          value={symbol}
          onValueChange={(v) => {
            if (didDrag.current) {
              didDrag.current = false;
              return;
            }
            if (v) onSymbolChange(v);
          }}
          className="flex h-8 w-max min-w-full flex-nowrap items-center gap-0.5 px-2"
        >
          {items.map((m) => {
            const change = m.change_24h;
            const vol = formatUsdCompact(m.volume_24h);
            const isDragging = dragging === m.symbol;
            const isOver = over === m.symbol && dragging != null && dragging !== m.symbol;

            return (
              <ToggleGroupItem
                key={m.symbol}
                value={m.symbol}
                draggable
                onDragStart={(e) => {
                  didDrag.current = false;
                  setDragging(m.symbol);
                  e.dataTransfer.effectAllowed = "move";
                  e.dataTransfer.setData("text/plain", m.symbol);
                }}
                onDrag={(e) => {
                  if (e.clientX !== 0 || e.clientY !== 0) didDrag.current = true;
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  if (over !== m.symbol) setOver(m.symbol);
                }}
                onDragLeave={() => {
                  if (over === m.symbol) setOver(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  const from = e.dataTransfer.getData("text/plain") || dragging;
                  if (from) move(from, m.symbol);
                  setDragging(null);
                  setOver(null);
                }}
                onDragEnd={() => {
                  setDragging(null);
                  setOver(null);
                }}
                className={cn(
                  "h-7 cursor-grab gap-1 px-1.5 active:cursor-grabbing data-[state=on]:bg-elevated/60 [&_svg:not([class*='size-'])]:size-3",
                  isDragging && "opacity-40",
                  isOver && "bg-elevated/40 ring-1 ring-bid/40"
                )}
              >
                <GripVertical className="text-muted opacity-40 group-hover/toggle:opacity-70 group-data-[state=on]/toggle:opacity-70" />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex items-center gap-1.5">
                      <span className="text-[11px] leading-none">{m.symbol}</span>
                      <Badge variant={changeVariant(change)} className="leading-none">
                        {formatPct(change)}
                      </Badge>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    {vol ? `${m.symbol} · 24h vol ${vol} · drag to reorder` : `${m.symbol} · drag to reorder`}
                  </TooltipContent>
                </Tooltip>
              </ToggleGroupItem>
            );
          })}
        </ToggleGroup>
      </ScrollArea>
    </div>
  );
});
