import { memo } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { logExplorerUrl } from "@/lib/explorer";
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
      <div className="grid h-6 shrink-0 grid-cols-[1fr_1fr_auto_3.25rem] px-2 font-mono text-sm leading-6 text-muted-foreground">
        <span>Price</span>
        <span>Size</span>
        <span className="text-right">Time</span>
        <span />
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {rows.length === 0 ? (
          <Empty className="rounded-none border-0 p-6">
            <EmptyHeader>
              <EmptyTitle>No prints</EmptyTitle>
              <EmptyDescription>Waiting for trades</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          rows.map((t, i) => {
            const logUrl = logExplorerUrl(t.tx_hash);
            return (
              <div
                key={`${t.tx_hash || t.timestamp}-${t.price}-${t.size}-${i}`}
                className="grid grid-cols-[1fr_1fr_auto_3.25rem] items-baseline px-2 py-0.5 font-mono text-base"
              >
                <span className={t.side === "buy" ? "text-bid" : "text-ask"}>
                  {formatPrice(t.price)}
                </span>
                <span className="text-muted-foreground">{formatSize(t.size)}</span>
                <span className="text-right text-muted-foreground">{formatClock(t.timestamp)}</span>
                {logUrl ? (
                  <a
                    href={logUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Open Log"
                    className="text-right font-sans text-sm text-muted-foreground hover:text-text"
                  >
                    explore
                  </a>
                ) : (
                  <span />
                )}
              </div>
            );
          })
        )}
      </ScrollArea>
    </div>
  );
});
