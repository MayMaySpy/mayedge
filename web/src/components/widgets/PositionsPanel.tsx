import { lazy, Suspense, useMemo, useRef, useState } from "react";
import { notifyErr, notifyOk, notifyWarn } from "@/lib/notify";
import { OverflowMenu } from "@/components/desk/OverflowMenu";
import { PanelCloseButton } from "@/components/desk/PanelHeader";
import { AssetsTab } from "@/components/widgets/account/AssetsTab";
import { AlgoOrdersPanel } from "@/components/widgets/AlgoOrdersPanel";
import { OrdersTab } from "@/components/widgets/account/OrdersTab";
import { PositionsTable } from "@/components/widgets/account/PositionsTable";
import { Button } from "@/components/ui/button";
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useToolbarFold } from "@/hooks/useToolbarFold";
import { useTradingReady } from "@/hooks/useTradingReady";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { api, isLongPosition, type Market, type Position } from "@/lib/api";
import { algoBlotter } from "@/lib/algos";
import { useJournalOpen, useLiveAccount, useLiveAlgos, useLiveBbo } from "@/lib/liveData";
import {
  positionNotional,
  exposure,
  pnlClass,
  positionsForClose,
  roePct,
  sortPositionRows,
  type CloseFilter,
  type PosSort,
} from "@/lib/positionsTable";
import { cn, formatPctAbs, formatSigned, formatUsd } from "@/lib/utils";

const TradeHistoryTab = lazy(() =>
  import("@/components/widgets/account/TradeHistoryTab").then((m) => ({
    default: m.TradeHistoryTab,
  })),
);
const FundingHistoryTab = lazy(() =>
  import("@/components/widgets/account/FundingHistoryTab").then((m) => ({
    default: m.FundingHistoryTab,
  })),
);
const JournalTab = lazy(() =>
  import("@/components/widgets/account/JournalTab").then((m) => ({
    default: m.JournalTab,
  })),
);

function HistoryTabFallback() {
  return (
    <div className="flex flex-col gap-1 p-2">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="h-5 animate-pulse bg-elevated" />
      ))}
    </div>
  );
}

interface PositionsPanelProps {
  market: Market | null;
  markets?: Market[];
  tradingEnabled: boolean;
  connected: boolean;
  onSymbolChange?: (symbol: string) => void;
  onClose?: () => void;
}

function n(value: string | undefined) {
  const x = parseFloat(value ?? "");
  return Number.isFinite(x) ? x : 0;
}

function liveMark(
  p: Position,
  selected: Market | null,
  liveSpot: number | null,
  markets: Market[]
): number {
  if (selected && p.market_index === selected.market_index && liveSpot && liveSpot > 0) {
    return liveSpot;
  }
  const fromAccount = n(p.mark_price);
  if (fromAccount > 0) return fromAccount;
  const m = markets.find((x) => x.market_index === p.market_index);
  return m?.last_trade_price || m?.mark_price || 0;
}

function livePnl(p: Position, mark: number): number {
  const size = n(p.size);
  const entry = n(p.entry_price);
  if (mark > 0 && entry > 0 && size !== 0) return (mark - entry) * size;
  return n(p.unrealized_pnl);
}

function placeCloseOrder(p: Position, markets: Market[], selected: Market | null) {
  const size = Math.abs(n(p.size));
  if (size <= 0) return Promise.resolve();
  const m = markets.find((x) => x.market_index === p.market_index) ?? selected;
  const decimals = m?.size_decimals ?? 4;
  return api.placeMarketOrder({
    market_index: p.market_index,
    side: isLongPosition(p) ? "sell" : "buy",
    size: trimQty(size, decimals) || String(size),
    slippage: 0.01,
    reduce_only: true,
  });
}

function CloseFilterButton({
  label,
  count,
  noun,
  className,
  disabled,
  onClick,
}: {
  label: string;
  count: number;
  noun: string;
  className?: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn("h-6 px-1.5 text-xs", className)}
          disabled={disabled}
          onClick={onClick}
        >
          {label}({count})
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        Close {count} {noun}. Does not stop algos or cancel orders.
      </TooltipContent>
    </Tooltip>
  );
}

export function PositionsPanel({
  market,
  markets = [],
  tradingEnabled,
  connected,
  onSymbolChange,
  onClose,
}: PositionsPanelProps) {
  const account = useLiveAccount();
  const algoBook = useLiveAlgos();
  const journalOpen = useJournalOpen();
  const { working: workingAlgos } = algoBlotter(algoBook);
  const bbo = useLiveBbo();
  const feed = useTradingReady({ connected });
  const [tab, setTab] = useState("positions");
  const [historyKind, setHistoryKind] = useState<"trades" | "funding">("trades");
  const [busy, setBusy] = useState<string | null>(null);
  const [posSort, setPosSort] = useState<PosSort>({ key: "notional", dir: "desc" });

  const cancelOrder = async (marketIndex: number, orderIndex: string | number) => {
    if (!tradingEnabled) {
      notifyErr("Trading not configured");
      return;
    }
    try {
      await api.cancelOrder(marketIndex, orderIndex);
      notifyOk("Order cancelled");
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Cancel failed");
    }
  };

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    if (!tradingEnabled) {
      notifyErr("Trading not configured");
      return false;
    }
    if (!feed.ready) {
      notifyErr(feed.reason ?? "Feed not ready");
      return false;
    }
    setBusy(key);
    try {
      await fn();
      notifyOk(ok);
      return true;
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Order failed");
      return false;
    } finally {
      setBusy(null);
    }
  };

  const closePosition = (p: Position) => {
    if (Math.abs(n(p.size)) <= 0) return;
    void run(`close-${p.market_index}`, () => placeCloseOrder(p, markets, market), `${p.symbol} closed`);
  };

  const openPositions = useMemo(
    () => (account?.positions ?? []).filter((p) => parseFloat(p.size) !== 0),
    [account]
  );

  const allOrders = useMemo(() => account?.open_orders ?? [], [account]);
  const openOrderCount = allOrders.length;

  const bid = parseFloat(bbo.bid ?? "");
  const ask = parseFloat(bbo.ask ?? "");
  const liveSpot =
    bid > 0 && ask > 0 ? (bid + ask) / 2 : bid > 0 ? bid : ask > 0 ? ask : null;

  const liveRows = useMemo(() => {
    return openPositions.map((p) => {
      const mark = liveMark(p, market, liveSpot, markets);
      const pnl = livePnl(p, mark);
      const sizeAbs = Math.abs(n(p.size));
      return {
        p,
        mark,
        pnl,
        marketIndex: p.market_index,
        sizeAbs,
        notional: positionNotional(n(p.size), mark, n(p.entry_price)),
        roe: roePct(p, pnl),
      };
    });
  }, [openPositions, market, liveSpot, markets]);

  const sortedRows = useMemo(
    () => sortPositionRows(liveRows, posSort, market?.market_index ?? null),
    [liveRows, posSort, market]
  );

  const usedMargin = openPositions.reduce((sum, p) => sum + n(p.allocated_margin), 0);
  const totalPnl = liveRows.reduce((sum, r) => sum + r.pnl, 0);
  const accountRoe = usedMargin > 0 ? (totalPnl / usedMargin) * 100 : null;
  const winners = positionsForClose(liveRows, "winners");
  const losers = positionsForClose(liveRows, "losers");
  const closeBlocked = !tradingEnabled || !feed.ready || busy != null;
  const closeChoices = [
    { filter: "winners", label: "W", noun: "winners", menu: "Close winners", count: winners.length, className: "text-bid hover:text-bid" },
    { filter: "losers", label: "L", noun: "losers", menu: "Close losers", count: losers.length, className: "text-ask hover:text-ask" },
    { filter: "all", label: "All", noun: "positions", menu: "Close all", count: liveRows.length, className: undefined },
  ] as const;

  const margin = n(account?.portfolio_margin);
  const exp = exposure(
    liveRows.map((r) => ({ notional: r.notional, long: isLongPosition(r.p) })),
    margin
  );
  const expTitle = [
    `Long ${formatUsd(exp.long)} · Short ${formatUsd(exp.short)}`,
    `Gross ${formatUsd(exp.gross)}${exp.leverage != null ? ` · ${exp.leverage.toFixed(2)}x the Portfolio margin` : ""}`,
  ].join("\n");
  const expReadout = (
    <span className="font-mono text-sm tabular-nums">
      {formatSigned(exp.net)}
      {exp.leverage != null && (
        <span className="ml-1 text-xs text-muted-foreground">({exp.leverage.toFixed(2)}x)</span>
      )}
    </span>
  );

  // A narrow panel folds the close chips into `…` first, then Exposure, then the uPnL readout.
  const barRef = useRef<HTMLDivElement>(null);
  const folded = useToolbarFold(
    barRef,
    3,
    `${winners.length}:${losers.length}:${liveRows.length}:${formatSigned(totalPnl).length}:${formatSigned(exp.net).length}`
  );
  const pnlReadout = (
    <span className={cn("font-mono text-sm tabular-nums", pnlClass(totalPnl))}>
      {formatSigned(totalPnl)}
      {accountRoe != null && <span className="ml-1 text-xs">({formatPctAbs(accountRoe)})</span>}
    </span>
  );

  const closeMany = async (filter: CloseFilter) => {
    if (!tradingEnabled) {
      notifyErr("Trading not configured");
      return;
    }
    if (!feed.ready) {
      notifyErr(feed.reason ?? "Feed not ready");
      return;
    }
    const targets = positionsForClose(liveRows, filter);
    if (!targets.length) return;
    setBusy(`close-${filter}`);
    let ok = 0;
    const errors: string[] = [];
    try {
      for (const { p } of targets) {
        try {
          await placeCloseOrder(p, markets, market);
          ok += 1;
        } catch (e) {
          errors.push(`${p.symbol}: ${e instanceof Error ? e.message : "failed"}`);
        }
      }
      const fail = errors.length;
      if (fail === 0) {
        notifyOk(`Closed ${ok}`);
      } else if (ok === 0) {
        notifyErr(errors.join("; "));
      } else {
        notifyWarn(`Closed ${ok}; ${fail} failed`, errors.join("; "));
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Tabs
        value={tab}
        onValueChange={setTab}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div ref={barRef} className="panel-drag flex h-8 shrink-0 items-center border-b border-rule pr-1">
          <TabsList className="min-w-0 overflow-hidden px-1">
            <TabsTrigger value="positions">
              Positions
              <span className="ml-1 font-mono text-xs text-muted-foreground">({openPositions.length})</span>
            </TabsTrigger>
            <TabsTrigger value="assets">
              Assets
              <span className="ml-1 font-mono text-xs text-muted-foreground">
                ({account?.assets?.length ?? 0})
              </span>
            </TabsTrigger>
            <TabsTrigger value="orders">
              Orders
              <span className="ml-1 font-mono text-xs text-muted-foreground">({openOrderCount})</span>
            </TabsTrigger>
            <TabsTrigger value="algos">
              Algos
              <span className="ml-1 font-mono text-xs text-muted-foreground">({workingAlgos.length})</span>
            </TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
            <TabsTrigger value="journal">Journal</TabsTrigger>
          </TabsList>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {folded < 1 ? (
              <div className="flex items-center gap-1">
                {closeChoices.map((c) => (
                  <CloseFilterButton
                    key={c.filter}
                    label={c.label}
                    count={c.count}
                    noun={c.noun}
                    className={c.className}
                    disabled={closeBlocked || c.count === 0}
                    onClick={() => void closeMany(c.filter)}
                  />
                ))}
              </div>
            ) : null}
            {folded < 2 && liveRows.length > 0 ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex cursor-default items-baseline gap-1.5 px-1">
                    <span className="text-sm text-muted-foreground">Net</span>
                    {expReadout}
                  </span>
                </TooltipTrigger>
                <TooltipContent className="whitespace-pre-line">
                  {`Exposure: net notional, long less short\n${expTitle}`}
                </TooltipContent>
              </Tooltip>
            ) : null}
            {folded < 3 ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex cursor-default items-baseline gap-1.5 px-1">
                    <span className="text-sm text-muted-foreground">uPnL</span>
                    {pnlReadout}
                  </span>
                </TooltipTrigger>
                <TooltipContent>Unrealized PnL across open positions</TooltipContent>
              </Tooltip>
            ) : null}
            {folded > 0 ? (
              <OverflowMenu label="More position controls">
                {folded > 1 && liveRows.length > 0 ? (
                  <DropdownMenuLabel className="flex items-baseline gap-1.5" title={expTitle}>
                    <span className="text-muted-foreground">Net</span>
                    {expReadout}
                  </DropdownMenuLabel>
                ) : null}
                {folded > 2 ? (
                  <>
                    <DropdownMenuLabel className="flex items-baseline gap-1.5">
                      <span className="text-muted-foreground">uPnL</span>
                      {pnlReadout}
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                {closeChoices.map((c) => (
                  <DropdownMenuItem
                    key={c.filter}
                    className={c.className}
                    disabled={closeBlocked || c.count === 0}
                    onSelect={() => void closeMany(c.filter)}
                  >
                    {c.menu} ({c.count})
                  </DropdownMenuItem>
                ))}
              </OverflowMenu>
            ) : null}
            {onClose ? <PanelCloseButton onClose={onClose} /> : null}
          </div>
        </div>

        <TabsContent value="positions" className="min-h-0 flex-1 px-2">
          <ScrollArea className="h-full">
            {!liveRows.length ? (
              <Empty className="rounded-none border-0 p-6">
                <EmptyHeader>
                  <EmptyTitle>No open positions</EmptyTitle>
                  <EmptyDescription>
                    {tradingEnabled ? "Start from the ticket" : "Connect an API key to view positions"}
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <PositionsTable
                rows={sortedRows}
                posSort={posSort}
                setPosSort={setPosSort}
                market={market}
                markets={markets}
                algoBook={algoBook}
                journalOpen={journalOpen}
                margin={margin}
                orders={allOrders}
                tradingEnabled={tradingEnabled}
                feedReady={feed.ready}
                busy={busy}
                run={run}
                onCancel={cancelOrder}
                onClosePosition={closePosition}
                onSymbolChange={onSymbolChange}
              />
            )}
          </ScrollArea>
        </TabsContent>

        <TabsContent value="assets" className="min-h-0 flex-1 px-2">
          <AssetsTab
            assets={account?.assets ?? []}
            markets={markets}
            tradingEnabled={tradingEnabled}
            onSymbolChange={onSymbolChange}
          />
        </TabsContent>

        <TabsContent value="orders" className="min-h-0 flex-1 px-2">
          <OrdersTab
            market={market}
            markets={markets}
            orders={allOrders}
            tradingEnabled={tradingEnabled}
            feed={feed}
            busy={busy}
            setBusy={setBusy}
            onCancel={cancelOrder}
            onSymbolChange={onSymbolChange}
          />
        </TabsContent>

        <TabsContent value="algos" className="mt-0 flex min-h-0 flex-1 flex-col">
          <AlgoOrdersPanel symbol={market?.symbol} tradingEnabled={tradingEnabled} />
        </TabsContent>

        <TabsContent value="history" className="flex min-h-0 flex-1 flex-col px-2">
          <ToggleGroup
            type="single"
            variant="seg"
            size="sm"
            spacing={0}
            value={historyKind}
            onValueChange={(v) => {
              if (v === "trades" || v === "funding") setHistoryKind(v);
            }}
            className="shrink-0 py-1"
          >
            <ToggleGroupItem value="trades">Trades</ToggleGroupItem>
            <ToggleGroupItem value="funding">Funding</ToggleGroupItem>
          </ToggleGroup>
          <Suspense fallback={<HistoryTabFallback />}>
            {historyKind === "trades" ? (
              <TradeHistoryTab
                market={market}
                tradingEnabled={tradingEnabled}
                active={tab === "history"}
                onSymbolChange={onSymbolChange}
              />
            ) : (
              <FundingHistoryTab
                market={market}
                tradingEnabled={tradingEnabled}
                active={tab === "history"}
                onSymbolChange={onSymbolChange}
              />
            )}
          </Suspense>
        </TabsContent>

        <TabsContent value="journal" className="mt-0 flex min-h-0 flex-1 flex-col">
          <Suspense fallback={<HistoryTabFallback />}>
            <JournalTab active={tab === "journal"} />
          </Suspense>
        </TabsContent>
      </Tabs>
    </div>
  );
}
