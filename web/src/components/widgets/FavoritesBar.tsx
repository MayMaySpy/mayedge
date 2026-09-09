import { memo, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, GripVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TokenMark } from "@/components/desk/TokenMark";
import type { Market } from "@/lib/api";
import {
  favChangeTone,
  favPriceLabel,
  insertIndexAtX,
  moveIdToIndex,
  scrollFadeX,
} from "@/lib/favoritesBar";
import { setFavorites, useFavorites } from "@/lib/favorites";
import { overlayQuote, useLiveQuotes } from "@/lib/liveData";
import { cn, formatPct } from "@/lib/utils";

interface FavoritesBarProps {
  markets: Market[];
  symbol: string;
  onSymbolChange: (symbol: string) => void;
}

const DRAG_PX = 4;
const toneClass = {
  bid: "text-bid",
  ask: "text-ask",
  muted: "text-muted",
} as const;

export const FavoritesBar = memo(function FavoritesBar({
  markets,
  symbol,
  onSymbolChange,
}: FavoritesBarProps) {
  const [favorites] = useFavorites();
  const quotes = useLiveQuotes();
  const [draft, setDraft] = useState<string[] | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [fade, setFade] = useState({ fadeL: 0, fadeR: 0, showRight: false });
  const rowRef = useRef<HTMLDivElement>(null);
  const orderRef = useRef<string[]>(favorites);
  const favoritesRef = useRef(favorites);
  favoritesRef.current = favorites;
  const dragRef = useRef<{
    id: string;
    pointerId: number;
    startX: number;
    moved: boolean;
  } | null>(null);

  const order = draft ?? favorites;
  const items = useMemo(() => {
    const bySym = new Map(markets.map((m) => [m.symbol, m]));
    return order.map((sym) => {
      const m = bySym.get(sym) ?? ({ symbol: sym } as Market);
      return overlayQuote(m, quotes[m.market_index]);
    });
  }, [order, markets, quotes]);

  const measure = () => {
    const el = rowRef.current;
    if (!el) return;
    setFade(scrollFadeX(el.scrollLeft, el.clientWidth, el.scrollWidth));
  };

  useEffect(() => {
    const el = rowRef.current;
    if (!el) return;
    measure();
    el.addEventListener("scroll", measure, { passive: true });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", measure);
      ro.disconnect();
    };
  }, [items.length]);

  if (items.length === 0) return null;

  const chipRects = () => {
    const row = rowRef.current;
    if (!row) return [];
    return Array.from(row.querySelectorAll<HTMLElement>("[data-fav]")).map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.dataset.fav ?? "", left: r.left, width: r.width };
    });
  };

  const onGripDown = (e: React.PointerEvent, id: string) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const pointerId = e.pointerId;
    dragRef.current = { id, pointerId, startX: e.clientX, moved: false };
    orderRef.current = [...(draft ?? favoritesRef.current)];

    const onMove = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return;
      const d = dragRef.current;
      if (!d) return;
      if (!d.moved && Math.abs(ev.clientX - d.startX) < DRAG_PX) return;
      ev.preventDefault();
      if (!d.moved) {
        d.moved = true;
        setDragging(d.id);
      }
      const to = insertIndexAtX(ev.clientX, chipRects(), d.id);
      const next = moveIdToIndex(orderRef.current, d.id, to);
      if (next === orderRef.current) return;
      orderRef.current = next;
      setDraft(next);
    };

    const onUp = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      const d = dragRef.current;
      dragRef.current = null;
      setDragging(null);
      setDraft(null);
      if (d?.moved) setFavorites(orderRef.current);
    };

    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  return (
    <div className="relative flex h-8 shrink-0 min-w-0 items-center border-b border-rule bg-panel">
      <div
        ref={rowRef}
        data-fade="x"
        className={cn(
          "scroll-hide flex h-full min-w-0 flex-1 items-center gap-x-2 overflow-x-auto px-2",
          dragging && "cursor-grabbing select-none"
        )}
        style={{ "--fade-l": `${fade.fadeL}px`, "--fade-r": `${fade.fadeR}px` } as React.CSSProperties}
      >
        {items.map((m) => {
          const on = m.symbol === symbol;
          const isDragging = dragging === m.symbol;
          const change = m.change_24h;
          const tone = favChangeTone(change);

          return (
            <div
              key={m.symbol}
              data-fav={m.symbol}
              className={cn("flex h-8 shrink-0 items-center", isDragging && "opacity-40")}
            >
              <div
                className={cn(
                  "flex items-center gap-1 overflow-visible rounded-full px-1 py-0.5 text-sm transition-colors hover:bg-elevated",
                  on && "bg-elevated"
                )}
              >
                <button
                  type="button"
                  onClick={() => onSymbolChange(m.symbol)}
                  className="flex cursor-pointer items-center gap-1"
                >
                  <TokenMark symbol={m.symbol} className="size-4" />
                  <span className="text-text">{m.symbol}</span>
                  <span className="tabular-nums text-muted">{favPriceLabel(m)}</span>
                  <span className={cn("tabular-nums", toneClass[tone])}>{formatPct(change)}</span>
                </button>
                <button
                  type="button"
                  aria-label={`Reorder ${m.symbol}`}
                  className="flex size-5 shrink-0 cursor-grab touch-none items-center justify-center text-muted hover:text-text active:cursor-grabbing"
                  onPointerDown={(e) => onGripDown(e, m.symbol)}
                >
                  <GripVertical className="size-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {fade.showRight ? (
        <Button
          type="button"
          variant="outline"
          size="icon"
          tabIndex={-1}
          aria-hidden
          className="absolute top-1/2 right-1 z-20 size-5 -translate-y-1/2 rounded-full"
          onClick={() => rowRef.current?.scrollBy({ left: 160, behavior: "smooth" })}
        >
          <ChevronRight data-icon />
        </Button>
      ) : null}
    </div>
  );
});
