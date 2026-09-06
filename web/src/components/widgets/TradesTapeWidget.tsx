import { memo } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatPrice, formatSize } from "@/lib/utils";
import { useLiveTrades } from "@/lib/liveData";

const TAPE_ROWS = 48;

function formatClock(ts: number): string {
  if (!ts) return "—";
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export const TradesTapeWidget = memo(function TradesTapeWidget({ onClose }: { onClose?: () => void }) {
  const trades = useLiveTrades();
  const rows = trades.length > TAPE_ROWS ? trades.slice(0, TAPE_ROWS) : trades;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader title="Trades" onClose={onClose} />
      <div className="grid h-5 shrink-0 grid-cols-3 px-2 font-mono text-[10px] leading-5 text-muted">
        <span>Price</span>
        <span>Size</span>
        <span className="text-right">Time</span>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {rows.length === 0 ? (
          <Empty className="rounded-none border-0 p-3">
            <EmptyDescription className="text-[11px] text-muted">Waiting…</EmptyDescription>
          </Empty>
        ) : (
          rows.map((t, i) => (
            <div
              key={`${t.timestamp}-${t.price}-${t.size}-${i}`}
              className="grid grid-cols-3 px-2 py-0.5 font-mono text-[11px]"
            >
              <span className={t.side === "buy" ? "text-bid" : "text-ask"}>
                {formatPrice(t.price)}
              </span>
              <span className="text-muted">{formatSize(t.size)}</span>
              <span className="text-right text-muted">{formatClock(t.timestamp)}</span>
            </div>
          ))
        )}
      </ScrollArea>
    </div>
  );
});
