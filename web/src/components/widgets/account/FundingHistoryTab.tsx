import { useState } from "react";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
} from "@/components/ui/table";
import { LoadingRows, LoadMore, ScopeToggle, type Scope } from "@/components/widgets/ListControls";
import { api, type Market } from "@/lib/api";
import { formatFundingPct } from "@/lib/marketPicker";
import { cn, formatSigned, formatSize, signClass } from "@/lib/utils";
import { utcDateTime } from "@/lib/utcTime";
import { rowPicksSymbol, usePagedHistory } from "./usePagedHistory";

const FETCH = (q: Parameters<typeof api.accountFunding>[0]) =>
  api.accountFunding(q).then((r) => ({ rows: r.fundings, next_cursor: r.next_cursor }));

interface FundingHistoryTabProps {
  market: Market | null;
  tradingEnabled: boolean;
  active: boolean;
  onSymbolChange?: (symbol: string) => void;
}

export function FundingHistoryTab({
  market,
  tradingEnabled,
  active,
  onSymbolChange,
}: FundingHistoryTabProps) {
  const [scope, setScope] = useState<Scope>("all");
  const marketIndex = scope === "pair" && market ? market.market_index : undefined;
  const { rows, cursor, loading, loadingMore, loadMore } = usePagedHistory(FETCH, {
    active,
    marketIndex,
    what: "funding",
  });

  const pick = rowPicksSymbol(onSymbolChange, market?.symbol);

  return (
    <ScrollArea className="min-h-0 flex-1">
      <ScopeToggle scope={scope} onScopeChange={setScope} pair={market?.symbol} className="mb-1.5" />

      {loading && rows.length === 0 ? (
        <LoadingRows />
      ) : !rows.length ? (
        <Empty className="rounded-none border-0 p-4">
          <EmptyDescription>
            {!tradingEnabled
              ? "Connect API key to view funding history"
              : scope === "pair" && market
                ? `No ${market.symbol} funding events yet`
                : "No funding events yet"}
          </EmptyDescription>
        </Empty>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-2.5">Time (UTC)</TableHead>
                <TableHead>Market</TableHead>
                <TableHead hideBelow="md">Side</TableHead>
                <TableHead hideBelow="sm" className="text-right">Size</TableHead>
                <TableHead hideBelow="lg" className="text-right">Rate</TableHead>
                <TableHead className="text-right">Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((f) => {
                const change = parseFloat(f.change);
                const rate = parseFloat(f.rate);
                const ratePct = Number.isFinite(rate) ? rate : null;
                return (
                  <TableRow
                    key={`${f.funding_id}-${f.timestamp}`}
                    onClick={pick(f.symbol)}
                    accent={f.side === "long" ? "bid" : "ask"}
                    className={cn(onSymbolChange && "cursor-pointer")}
                  >
                    <TableCell className="pl-2.5 text-muted-foreground">{utcDateTime(f.timestamp)}</TableCell>
                    <TableCell>
                      <TableName>{f.symbol}</TableName>
                    </TableCell>
                    <TableCell hideBelow="md" className={f.side === "long" ? "text-bid" : "text-ask"}>
                      {f.side}
                    </TableCell>
                    <TableCell hideBelow="sm" className="text-right">{formatSize(f.position_size)}</TableCell>
                    <TableCell hideBelow="lg" className="text-right text-muted-foreground">
                      {formatFundingPct(ratePct)}
                    </TableCell>
                    <TableCell className={cn("text-right", signClass(change))}>
                      {formatSigned(f.change, 4)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <LoadMore cursor={cursor} loading={loadingMore} onLoad={() => void loadMore()} />
        </>
      )}
    </ScrollArea>
  );
}
