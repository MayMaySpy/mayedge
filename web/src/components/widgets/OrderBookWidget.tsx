import { memo, useEffect, useMemo, useRef, useState } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { formatPrice, formatSize } from "@/lib/utils";
import { theme } from "@/lib/theme";
import { useLiveBook, type OrderBookLevel } from "@/lib/liveData";

interface DepthRow {
  price: string;
  size: number;
  cum: number;
}

const ROW_H = 18;

/** Backend already sends bids desc / asks asc; only parse + cum for visible depth. */
function toRows(levels: OrderBookLevel[], depth: number): DepthRow[] {
  const rows: DepthRow[] = [];
  let cum = 0;
  for (let i = 0; i < levels.length && rows.length < depth; i++) {
    const size = parseFloat(levels[i].size) || 0;
    if (size <= 0) continue;
    cum += size;
    rows.push({ price: levels[i].price, size, cum });
  }
  return rows;
}

const Slot = memo(function Slot({
  price,
  size,
  cum,
  maxCum,
  side,
}: {
  price: string | null;
  size: number;
  cum: number;
  maxCum: number;
  side: "bid" | "ask";
}) {
  const color = side === "bid" ? theme.bid : theme.ask;
  const pct = price != null && maxCum > 0 ? (cum / maxCum) * 100 : 0;

  return (
    <div className="relative grid min-h-0 flex-1 grid-cols-2 items-center px-2 font-mono text-[11px] leading-none">
      {price != null && (
        <>
          <div
            className="absolute inset-y-0 right-0 opacity-15"
            style={{ width: `${pct}%`, background: color }}
          />
          <span className={side === "bid" ? "text-bid" : "text-ask"}>
            {formatPrice(price)}
          </span>
          <span className="text-right text-muted">{formatSize(size)}</span>
        </>
      )}
    </div>
  );
});

export const OrderBookWidget = memo(function OrderBookWidget({ onClose }: { onClose?: () => void }) {
  const { bids, asks } = useLiveBook();
  const rootRef = useRef<HTMLDivElement>(null);
  const [depth, setDepth] = useState(12);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const measure = () => {
      const h = el.clientHeight;
      const usable = Math.max(0, h - 56);
      setDepth(Math.max(4, Math.floor(usable / 2 / ROW_H)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const bidRows = useMemo(() => toRows(bids, depth), [bids, depth]);
  const askRows = useMemo(() => toRows(asks, depth), [asks, depth]);
  const maxCum = Math.max(bidRows[depth - 1]?.cum ?? 0, askRows[depth - 1]?.cum ?? 0, 1);

  const bestBid = bidRows[0] ? parseFloat(bidRows[0].price) : 0;
  const bestAsk = askRows[0] ? parseFloat(askRows[0].price) : 0;
  const mid = bestAsk && bestBid ? (bestAsk + bestBid) / 2 : 0;
  const spreadPct = mid > 0 && bestAsk > bestBid ? ((bestAsk - bestBid) / mid) * 100 : null;

  const askIndices = useMemo(() => {
    const idx: number[] = [];
    for (let i = depth - 1; i >= 0; i--) idx.push(i);
    return idx;
  }, [depth]);

  return (
    <div ref={rootRef} className="flex h-full min-h-0 flex-col">
      <PanelHeader title="Book" onClose={onClose} />
      <div className="grid h-5 shrink-0 grid-cols-2 px-2 font-mono text-[10px] leading-5 text-muted">
        <span>Price</span>
        <span className="text-right">Size</span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {askIndices.map((level, i) => {
          const row = askRows[level];
          return (
            <Slot
              key={`a${i}`}
              price={row?.price ?? null}
              size={row?.size ?? 0}
              cum={row?.cum ?? 0}
              maxCum={maxCum}
              side="ask"
            />
          );
        })}
      </div>
      <div className="flex h-6 shrink-0 items-center justify-center border-y border-rule bg-elevated/30 font-mono text-[11px]">
        <span className="text-text">{mid ? formatPrice(mid, 6) : "—"}</span>
        <span className="ml-2 text-muted">
          {spreadPct != null
            ? `${spreadPct.toFixed(spreadPct < 0.01 ? 4 : 3)}%`
            : ""}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {Array.from({ length: depth }, (_, i) => {
          const row = bidRows[i];
          return (
            <Slot
              key={`b${i}`}
              price={row?.price ?? null}
              size={row?.size ?? 0}
              cum={row?.cum ?? 0}
              maxCum={maxCum}
              side="bid"
            />
          );
        })}
      </div>
    </div>
  );
});
