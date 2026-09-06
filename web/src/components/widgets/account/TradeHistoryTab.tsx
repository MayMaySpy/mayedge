import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, type AccountTrade, type Market } from "@/lib/api";
import { useLiveAccountTrades } from "@/lib/liveData";
import { cn, formatPrice, formatSigned, formatSize } from "@/lib/utils";

function tradeTime(ts: number) {
  if (!ts) return "—";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function mergeTrades(rest: AccountTrade[], live: AccountTrade[]): AccountTrade[] {
  const byId = new Map<string, AccountTrade>();
  const pick = (a: AccountTrade, b: AccountTrade): AccountTrade => {
    const pnlA = Math.abs(parseFloat(a.pnl) || 0);
    const pnlB = Math.abs(parseFloat(b.pnl) || 0);
    const feeA = Math.abs(parseFloat(a.fee) || 0);
    const feeB = Math.abs(parseFloat(b.fee) || 0);
    return {
      ...b,
      ...a,
      pnl: pnlA >= pnlB ? a.pnl : b.pnl,
      fee: feeA >= feeB ? a.fee : b.fee,
      symbol: a.symbol || b.symbol,
      side: a.side || b.side,
    };
  };
  for (const row of rest) {
    if (row.trade_id) byId.set(row.trade_id, row);
  }
  for (const row of live) {
    if (!row.trade_id) continue;
    const prev = byId.get(row.trade_id);
    byId.set(row.trade_id, prev ? pick(row, prev) : row);
  }
  return [...byId.values()].sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
}

function pnlClass(value: number) {
  if (value > 0) return "text-bid";
  if (value < 0) return "text-ask";
  return "text-muted";
}

interface TradeHistoryTabProps {
  market: Market | null;
  tradingEnabled: boolean;
  active: boolean;
  onSymbolChange?: (symbol: string) => void;
}

export function TradeHistoryTab({
  market,
  tradingEnabled,
  active,
  onSymbolChange,
}: TradeHistoryTabProps) {
  const live = useLiveAccountTrades();
  const [scope, setScope] = useState<"all" | "pair">("all");
  const [rows, setRows] = useState<AccountTrade[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const marketIndex = scope === "pair" && market ? market.market_index : undefined;

  const loadPage = useCallback(
    async (nextCursor?: string | null) => {
      const more = !!nextCursor;
      if (more) setLoadingMore(true);
      else setLoading(true);
      try {
        const page = await api.accountTrades({
          market_index: marketIndex ?? null,
          cursor: nextCursor ?? undefined,
          limit: 50,
        });
        setCursor(page.next_cursor);
        setRows((prev) => (more ? [...prev, ...page.trades] : page.trades));
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to load trades");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [marketIndex]
  );

  useEffect(() => {
    if (!active) return;
    void loadPage(null);
  }, [active, loadPage]);

  const merged = useMemo(() => {
    const filteredLive =
      marketIndex != null ? live.filter((t) => t.market_index === marketIndex) : live;
    return mergeTrades(rows, filteredLive);
  }, [rows, live, marketIndex]);

  return (
    <ScrollArea className="h-full">
      <ToggleGroup
        type="single"
        variant="seg"
        size="sm"
        spacing={0}
        value={scope}
        onValueChange={(v) => {
          if (v === "all" || v === "pair") setScope(v);
        }}
        className="mb-1.5"
      >
        <ToggleGroupItem value="all">All</ToggleGroupItem>
        <ToggleGroupItem value="pair" disabled={!market}>
          {market?.symbol ?? "Pair"}
        </ToggleGroupItem>
      </ToggleGroup>

      {loading && merged.length === 0 ? (
        <div className="flex flex-col gap-1 p-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-5 animate-pulse bg-elevated" />
          ))}
        </div>
      ) : !merged.length ? (
        <Empty className="rounded-none border-0 p-4">
          <EmptyDescription className="text-[11px] text-muted">
            {!tradingEnabled
              ? "Connect API key to view trade history"
              : scope === "pair" && market
                ? `No ${market.symbol} fills yet`
                : "No fills yet"}
          </EmptyDescription>
        </Empty>
      ) : (
        <>
          <Table className="font-mono text-[11px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Time</TableHead>
                <TableHead>Market</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Fee</TableHead>
                <TableHead className="text-right">PnL</TableHead>
                <TableHead className="text-right">Role</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {merged.map((t) => {
                const fee = parseFloat(t.fee);
                const pnl = parseFloat(t.pnl);
                return (
                  <TableRow
                    key={t.trade_id}
                    onClick={
                      onSymbolChange
                        ? () => {
                            if (market?.symbol !== t.symbol) onSymbolChange(t.symbol);
                          }
                        : undefined
                    }
                    className={cn(onSymbolChange && "cursor-pointer")}
                  >
                    <TableCell className="text-muted">{tradeTime(t.timestamp)}</TableCell>
                    <TableCell>{t.symbol}</TableCell>
                    <TableCell className={t.side === "buy" ? "text-bid" : "text-ask"}>
                      {t.side}
                    </TableCell>
                    <TableCell className="text-right">{formatSize(t.size)}</TableCell>
                    <TableCell className="text-right">{formatPrice(t.price)}</TableCell>
                    <TableCell className={cn("text-right", pnlClass(-fee))}>
                      {formatSigned(-fee)}
                    </TableCell>
                    <TableCell className={cn("text-right", pnlClass(pnl))}>
                      {formatSigned(t.pnl)}
                    </TableCell>
                    <TableCell className="text-right text-muted">
                      {t.is_maker ? "maker" : "taker"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {cursor && (
            <div className="flex justify-center py-2">
              <Button
                variant="outline"
                size="sm"
                disabled={loadingMore}
                onClick={() => void loadPage(cursor)}
              >
                {loadingMore ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </>
      )}
    </ScrollArea>
  );
}
