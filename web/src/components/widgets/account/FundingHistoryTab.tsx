import { useCallback, useEffect, useState } from "react";
import { notifyErr } from "@/lib/notify";
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
import { api, type AccountFunding, type Market } from "@/lib/api";
import { cn, formatPct, formatSigned, formatSize } from "@/lib/utils";

function fundingTime(ts: number) {
  if (!ts) return "—";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function pnlClass(value: number) {
  if (value > 0) return "text-bid";
  if (value < 0) return "text-ask";
  return "text-muted";
}

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
  const [scope, setScope] = useState<"all" | "pair">("all");
  const [page, setPage] = useState<{
    key: string | null;
    rows: AccountFunding[];
    cursor: string | null;
  }>({ key: null, rows: [], cursor: null });
  const [loadingMore, setLoadingMore] = useState(false);

  const marketIndex = scope === "pair" && market ? market.market_index : undefined;
  const queryKey = String(marketIndex ?? "all");
  const rows = page.key === queryKey ? page.rows : [];
  const cursor = page.key === queryKey ? page.cursor : null;
  const loading = active && page.key !== queryKey;

  const loadMore = useCallback(async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const result = await api.accountFunding({
        market_index: marketIndex ?? null,
        cursor,
        limit: 50,
      });
      setPage((prev) => ({
        key: queryKey,
        rows: prev.key === queryKey ? [...prev.rows, ...result.fundings] : result.fundings,
        cursor: result.next_cursor,
      }));
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Failed to load funding");
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, marketIndex, queryKey]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void (async () => {
      try {
        const result = await api.accountFunding({
          market_index: marketIndex ?? null,
          limit: 50,
        });
        if (cancelled) return;
        setPage({
          key: queryKey,
          rows: result.fundings,
          cursor: result.next_cursor,
        });
      } catch (e) {
        if (cancelled) return;
        notifyErr(e instanceof Error ? e.message : "Failed to load funding");
        setPage({ key: queryKey, rows: [], cursor: null });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, marketIndex, queryKey]);

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

      {loading && rows.length === 0 ? (
        <div className="flex flex-col gap-1 p-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-5 animate-pulse bg-elevated" />
          ))}
        </div>
      ) : !rows.length ? (
        <Empty className="rounded-none border-0 p-4">
          <EmptyDescription className="text-[11px] text-muted">
            {!tradingEnabled
              ? "Connect API key to view funding history"
              : scope === "pair" && market
                ? `No ${market.symbol} funding events yet`
                : "No funding events yet"}
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
                <TableHead className="text-right">Rate</TableHead>
                <TableHead className="text-right">Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((f) => {
                const change = parseFloat(f.change);
                const rate = parseFloat(f.rate);
                const ratePct = Number.isFinite(rate) ? rate * 100 : null;
                return (
                  <TableRow
                    key={`${f.funding_id}-${f.timestamp}`}
                    onClick={
                      onSymbolChange
                        ? () => {
                            if (market?.symbol !== f.symbol) onSymbolChange(f.symbol);
                          }
                        : undefined
                    }
                    className={cn(onSymbolChange && "cursor-pointer")}
                  >
                    <TableCell className="text-muted">{fundingTime(f.timestamp)}</TableCell>
                    <TableCell>{f.symbol}</TableCell>
                    <TableCell className={f.side === "long" ? "text-bid" : "text-ask"}>
                      {f.side}
                    </TableCell>
                    <TableCell className="text-right">{formatSize(f.position_size)}</TableCell>
                    <TableCell className="text-right text-muted">
                      {ratePct != null ? formatPct(ratePct, 4) : "—"}
                    </TableCell>
                    <TableCell className={cn("text-right", pnlClass(change))}>
                      {formatSigned(f.change, 4)}
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
                onClick={() => void loadMore()}
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
