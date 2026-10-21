import { memo } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { logExplorerUrl } from "@/lib/explorer";
import { cn, formatPrice, formatSize } from "@/lib/utils";
import { utcClock } from "@/lib/utcTime";
import { useLiveTrades } from "@/lib/liveData";

const TAPE_ROWS = 48;

export const TradesTapeWidget = memo(function TradesTapeWidget({
  priceDecimals,
  onClose,
}: {
  /** The market's tick; the tape holds only the selected market's prints. */
  priceDecimals?: number;
  onClose?: () => void;
}) {
  const trades = useLiveTrades();
  const rows = trades.length > TAPE_ROWS ? trades.slice(0, TAPE_ROWS) : trades;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader title="Trades" onClose={onClose} />
      <ScrollArea className="min-h-0 flex-1">
        {rows.length === 0 ? (
          <Empty className="rounded-none border-0 p-6">
            <EmptyHeader>
              <EmptyTitle>No prints</EmptyTitle>
              <EmptyDescription>Waiting for trades</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-panel">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead hideBelow="4xs" className="text-right">Time (UTC)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((t, i) => {
                const logUrl = logExplorerUrl(t.tx_hash);
                return (
                  <TableRow key={`${t.tx_hash || t.timestamp}-${t.price}-${t.size}-${i}`}>
                    <TableCell className={cn("text-right", t.side === "buy" ? "text-bid" : "text-ask")}>
                      {formatPrice(t.price, priceDecimals)}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">{formatSize(t.size)}</TableCell>
                    <TableCell hideBelow="4xs" className="text-right text-muted-foreground">
                      {logUrl ? (
                        <a
                          href={logUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Open Log"
                          className="hover:text-text hover:underline"
                        >
                          {utcClock(t.timestamp)}
                        </a>
                      ) : (
                        utcClock(t.timestamp)
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </ScrollArea>
    </div>
  );
});
