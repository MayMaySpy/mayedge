import { memo, useEffect, useMemo, useRef, useState } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { cn, formatPct, formatPrice, formatSize, formatUsdCompact } from "@/lib/utils";
import type { Market } from "@/lib/api";
import { useLiveBook } from "@/lib/liveData";
import {
  depthBarWidths,
  sideMaxTotal,
  toDepthRows,
  walkMovePct,
  walkNotional,
  type NotionalWalk,
} from "@/lib/orderBookDepth";
import { pickLimitPrice } from "@/lib/ticketFill";

const WALK_USD_KEY = "mayedge-book-walk-usd";
const DEFAULT_WALK_USD = 10_000;

function loadWalkUsd(): number {
  try {
    const n = parseFloat(localStorage.getItem(WALK_USD_KEY) ?? "");
    if (!Number.isFinite(n) || n < 1000) return DEFAULT_WALK_USD;
    return Math.round(n / 1000) * 1000;
  } catch {
    return DEFAULT_WALK_USD;
  }
}

function persistWalkUsd(n: number) {
  try {
    localStorage.setItem(WALK_USD_KEY, String(n));
  } catch {
    /* ignore */
  }
}

function walkHint(walk: NotionalWalk | null, decimals: number): string {
  if (!walk) return "No book";
  const fill = formatUsdCompact(walk.filledUsd) || `$${Math.round(walk.filledUsd)}`;
  const avg = formatPrice(walk.avgPrice, decimals);
  const worst = formatPrice(walk.worstPrice, decimals);
  if (!walk.complete) return `fills ${fill} · avg ${avg} · worst ${worst}`;
  return `avg ${avg} · worst ${worst}`;
}

function hitKind(walk: NotionalWalk | null, index: number): "full" | "partial" | null {
  if (!walk || walk.lastIndex < 0) return null;
  if (index < walk.lastIndex) return "full";
  if (index === walk.lastIndex) return walk.lastFrac >= 1 - 1e-9 ? "full" : "partial";
  return null;
}

const ROW_H = 16;
const COLS = "grid-cols-[30%_30%_40%]";

const Slot = memo(function Slot({
  price,
  size,
  total,
  maxTotal,
  side,
  decimals,
  hit,
  hitFrac,
}: {
  price: string | null;
  size: number;
  total: number;
  maxTotal: number;
  side: "bid" | "ask";
  decimals: number;
  hit: "full" | "partial" | null;
  hitFrac: number;
}) {
  if (price == null) {
    return <div className={cn("relative h-(--ob-row-height,1.25rem) w-full shrink-0", COLS)} />;
  }

  const { cumPct, sizePct } = depthBarWidths(size, total, maxTotal);

  return (
    <button
      type="button"
      className={cn(
        "group relative z-0 flex h-(--ob-row-height,1.25rem) w-full shrink-0 flex-col hover:bg-foreground/[0.035]",
        "hover:[&~button]:bg-foreground/2"
      )}
      title="Set limit price"
      aria-label={`Set limit price ${price}`}
      onClick={() => pickLimitPrice(price)}
    >
      <div
        className={cn(
          "relative grid h-full w-full items-center px-1 text-right font-mono text-sm leading-none",
          COLS
        )}
      >
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-y-0 left-0 z-2 hidden w-0.5 group-hover:block",
            side === "bid" ? "bg-bid" : "bg-ask"
          )}
        />
        {cumPct > 0 ? (
          <div
            className={cn(
              "absolute inset-y-0 left-0 z-0 flex justify-start",
              side === "bid" ? "bg-bid/8" : "bg-ask/8"
            )}
            style={{ width: `${cumPct}%` }}
          >
            <div
              className={cn("h-full min-w-px", side === "bid" ? "bg-bid/[0.14]" : "bg-ask/[0.14]")}
              style={{ width: `${sizePct}%` }}
            />
          </div>
        ) : null}
        {hit ? (
          <div
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-y-0 left-0 z-0",
              side === "bid" ? "bg-bid/20" : "bg-ask/20"
            )}
            style={{ width: hit === "full" ? "100%" : `${Math.max(hitFrac, 0) * 100}%` }}
          />
        ) : null}
        <span
          className={cn(
            "z-1 text-left tabular-nums group-hover:font-medium",
            side === "bid" ? "text-bid" : "text-ask"
          )}
        >
          {formatPrice(price, decimals)}
        </span>
        <span className="z-1 tabular-nums text-muted-foreground group-hover:font-medium group-hover:text-foreground">
          {formatSize(size)}
        </span>
        <span className="z-1 tabular-nums text-muted-foreground group-hover:font-medium group-hover:text-foreground">
          {formatSize(total)}
        </span>
      </div>
    </button>
  );
});

export const OrderBookWidget = memo(function OrderBookWidget({
  market,
  onClose,
}: {
  market?: Market | null;
  onClose?: () => void;
}) {
  const { bids, asks } = useLiveBook();
  const rootRef = useRef<HTMLDivElement>(null);
  const [depth, setDepth] = useState(12);
  const [usd, setUsd] = useState(loadWalkUsd);
  const [preview, setPreview] = useState<"bid" | "ask" | null>(null);
  const decimals = market?.price_decimals ?? 4;
  const symbol = market?.symbol ?? "";

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const measure = () => {
      const h = el.clientHeight;
      const usable = Math.max(0, h - 92);
      setDepth(Math.max(4, Math.floor(usable / 2 / ROW_H)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const bidRows = useMemo(() => toDepthRows(bids, depth), [bids, depth]);
  const askRows = useMemo(() => toDepthRows(asks, depth), [asks, depth]);
  const maxBidTotal = sideMaxTotal(bidRows);
  const maxAskTotal = sideMaxTotal(askRows);

  const bestBid = bidRows[0] ? parseFloat(bidRows[0].price) : 0;
  const bestAsk = askRows[0] ? parseFloat(askRows[0].price) : 0;
  const spread = bestAsk > 0 && bestBid > 0 ? bestAsk - bestBid : 0;
  const mid = spread > 0 ? (bestAsk + bestBid) / 2 : 0;
  const spreadPct = mid > 0 ? (spread / mid) * 100 : null;

  const buyWalk = useMemo(() => walkNotional(asks, usd), [asks, usd]);
  const sellWalk = useMemo(() => walkNotional(bids, usd), [bids, usd]);
  const buyPct = walkMovePct(buyWalk, mid);
  const sellPct = walkMovePct(sellWalk, mid);
  const usdK = Math.max(1, Math.round(usd / 1000));

  const farToNear = useMemo(() => {
    const idx: number[] = [];
    for (let i = depth - 1; i >= 0; i--) idx.push(i);
    return idx;
  }, [depth]);

  return (
    <div ref={rootRef} className="flex h-full min-h-0 flex-col">
      <PanelHeader title="Book" onClose={onClose} className="relative">
        <div className="pointer-events-none absolute inset-x-10 inset-y-0 flex items-center justify-center">
          <div className="pointer-events-auto flex min-w-0 items-center gap-1">
            <button
              type="button"
              title={walkHint(buyWalk, decimals)}
              aria-label={`Buy ${usdK}k impact`}
              className={cn(
                "shrink-0 font-mono text-xs tabular-nums leading-none",
                buyPct == null ? "text-muted-foreground" : "text-bid"
              )}
              onMouseEnter={() => setPreview("ask")}
              onMouseLeave={() => setPreview(null)}
              onFocus={() => setPreview("ask")}
              onBlur={() => setPreview(null)}
            >
              {buyPct == null ? "—" : formatPct(buyPct)}
            </button>
            <div className="flex items-center gap-px">
              <label htmlFor="book-walk-k" className="sr-only">
                Impact notional in thousands of USD
              </label>
              <input
                id="book-walk-k"
                type="number"
                min={1}
                step={1}
                value={usdK}
                onChange={(e) => {
                  const k = e.target.valueAsNumber;
                  if (!Number.isFinite(k) || k < 1) return;
                  const next = Math.round(k) * 1000;
                  setUsd(next);
                  persistWalkUsd(next);
                }}
                className="h-5 w-10 cursor-text border-0 bg-transparent p-0 text-right font-mono text-sm tabular-nums text-foreground outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <span className="text-xs text-muted-foreground">k</span>
            </div>
            <button
              type="button"
              title={walkHint(sellWalk, decimals)}
              aria-label={`Sell ${usdK}k impact`}
              className={cn(
                "shrink-0 font-mono text-xs tabular-nums leading-none",
                sellPct == null ? "text-muted-foreground" : "text-ask"
              )}
              onMouseEnter={() => setPreview("bid")}
              onMouseLeave={() => setPreview(null)}
              onFocus={() => setPreview("bid")}
              onBlur={() => setPreview(null)}
            >
              {sellPct == null ? "—" : formatPct(sellPct)}
            </button>
          </div>
        </div>
      </PanelHeader>
      <div className="flex min-h-0 flex-1 flex-col px-2 pb-1.5">
        <div
          className={cn(
            "grid h-6 shrink-0 items-center border-b-[0.5px] border-border px-1 font-mono text-xs uppercase leading-6 text-muted-foreground",
            COLS
          )}
        >
          <span>Price</span>
          <span className="text-right whitespace-nowrap">
            Size{symbol ? <span className="ml-1 text-foreground/70">{symbol}</span> : null}
          </span>
          <span className="text-right">Total</span>
        </div>
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto_minmax(0,1fr)] overflow-hidden">
          <div
            className="flex min-h-0 flex-col justify-end overflow-hidden"
            style={{ ["--ob-row-height" as string]: `calc(100% / ${Math.max(depth, 1)})` }}
          >
            {farToNear.map((level) => {
              const row = askRows[level];
              return (
                <Slot
                  key={`a${level}`}
                  price={row?.price ?? null}
                  size={row?.size ?? 0}
                  total={row?.total ?? 0}
                  maxTotal={maxAskTotal}
                  side="ask"
                  decimals={decimals}
                  hit={preview === "ask" ? hitKind(buyWalk, level) : null}
                  hitFrac={buyWalk?.lastFrac ?? 0}
                />
              );
            })}
          </div>
          <div
            className={cn(
              "grid shrink-0 items-center border-y-[0.5px] border-border bg-secondary/40 px-1 py-0.5 font-mono text-sm",
              COLS
            )}
          >
            {mid > 0 ? (
              <>
                <button
                  type="button"
                  className="text-left tabular-nums text-foreground"
                  title="Set limit to mid"
                  onClick={() => pickLimitPrice(String(mid))}
                >
                  {formatPrice(spread, Math.min(decimals + 1, 6))}
                </button>
                <span className="text-right text-xs uppercase text-muted-foreground">Spread</span>
                <span className="text-right tabular-nums text-muted-foreground">
                  {spreadPct != null ? `${spreadPct.toFixed(spreadPct < 0.01 ? 4 : 3)}%` : ""}
                </span>
              </>
            ) : (
              <span className="col-span-3 text-center text-muted-foreground">No book</span>
            )}
          </div>
          <div
            className="flex min-h-0 flex-col-reverse justify-end overflow-hidden"
            style={{ ["--ob-row-height" as string]: `calc(100% / ${Math.max(depth, 1)})` }}
          >
            {farToNear.map((level) => {
              const row = bidRows[level];
              return (
                <Slot
                  key={`b${level}`}
                  price={row?.price ?? null}
                  size={row?.size ?? 0}
                  total={row?.total ?? 0}
                  maxTotal={maxBidTotal}
                  side="bid"
                  decimals={decimals}
                  hit={preview === "bid" ? hitKind(sellWalk, level) : null}
                  hitFrac={sellWalk?.lastFrac ?? 0}
                />
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
});
