import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { notifyErr, notifyOk } from "@/lib/notify";
import { PanelCloseButton } from "@/components/desk/PanelHeader";
import { FundingHistoryTab } from "@/components/widgets/account/FundingHistoryTab";
import { TradeHistoryTab } from "@/components/widgets/account/TradeHistoryTab";
import { AlgoOrdersPanel } from "@/components/widgets/AlgoOrdersPanel";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTradingReady } from "@/hooks/useTradingReady";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { api, isLongPosition, type Market, type Position } from "@/lib/api";
import { algoBlotter, algoOrderKind, isAlgoClientOrder } from "@/lib/algos";
import { useLiveAccount, useLiveAlgos, useLiveBbo } from "@/lib/liveData";
import {
  nextPosSort,
  positionNotional,
  sortPositionRows,
  type PosSort,
  type PosSortKey,
} from "@/lib/positionsTable";
import { cn, formatPct, formatPrice, formatSigned, formatSize, formatUsdCompact } from "@/lib/utils";

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

function roePct(p: Position, pnl: number): number | null {
  const margin = n(p.allocated_margin);
  if (margin > 0) return (pnl / margin) * 100;
  const notional = Math.abs(n(p.size)) * n(p.entry_price);
  const lev = p.leverage || 0;
  if (notional > 0 && lev > 0) return (pnl / (notional / lev)) * 100;
  return null;
}

function liqCushion(p: Position, mark: number): number | null {
  const liq = n(p.liquidation_price);
  const size = n(p.size);
  if (liq <= 0 || mark <= 0 || size === 0) return null;
  return size > 0 ? ((mark - liq) / mark) * 100 : ((liq - mark) / mark) * 100;
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

function pnlClass(value: number) {
  if (value > 0) return "text-bid";
  if (value < 0) return "text-ask";
  return "text-muted";
}

function formatNotional(value: number): string {
  if (!(value > 0)) return "—";
  return formatUsdCompact(value) || `$${value.toFixed(0)}`;
}

function SortHead({
  label,
  column,
  sort,
  onSort,
  title,
}: {
  label: string;
  column: PosSortKey;
  sort: PosSort;
  onSort: (key: PosSortKey) => void;
  title?: string;
}) {
  const active = sort.key === column;
  return (
    <TableHead className="text-right">
      <button
        type="button"
        title={title ?? `Sort by ${label}`}
        onClick={() => onSort(column)}
        className={cn(
          "ml-auto inline-flex items-center gap-0.5 hover:text-text",
          active && "text-text"
        )}
      >
        {label}
        {active ? (sort.dir === "desc" ? " ↓" : " ↑") : null}
      </button>
    </TableHead>
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
  const { working: workingAlgos } = algoBlotter(algoBook);
  const bbo = useLiveBbo();
  const feed = useTradingReady({ connected });
  const [tab, setTab] = useState("positions");
  const [orderScope, setOrderScope] = useState<"all" | "pair">("all");
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

  const cancelPair = async () => {
    if (!market) return;
    try {
      await api.cancelAll(market.market_index);
      notifyOk(`Cancelled ${market.symbol} orders`);
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Cancel pair failed");
    }
  };

  const cancelAll = async () => {
    try {
      await api.cancelAll(null);
      notifyOk("Cancelled all orders");
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Cancel all failed");
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
    const size = Math.abs(n(p.size));
    if (size <= 0) return;
    const m = markets.find((x) => x.market_index === p.market_index) ?? market;
    const decimals = m?.size_decimals ?? 4;
    const closeSide = isLongPosition(p) ? "sell" : "buy";
    void run(
      `close-${p.market_index}`,
      () =>
        api.placeMarketOrder({
          market_index: p.market_index,
          side: closeSide,
          size: trimQty(size, decimals) || String(size),
          slippage: 0.01,
          reduce_only: true,
        }),
      `${p.symbol} closed`
    );
  };

  const openPositions = useMemo(
    () => (account?.positions ?? []).filter((p) => parseFloat(p.size) !== 0),
    [account]
  );

  const allOrders = useMemo(() => account?.open_orders ?? [], [account]);
  const userOrders = useMemo(
    () => allOrders.filter((o) => !isAlgoClientOrder(o.client_order_index)),
    [allOrders]
  );
  const pairOrders = useMemo(
    () => (market ? allOrders.filter((o) => o.market_index === market.market_index) : allOrders),
    [allOrders, market]
  );
  const pairUserOrders = useMemo(
    () => (market ? userOrders.filter((o) => o.market_index === market.market_index) : userOrders),
    [userOrders, market]
  );

  const listedAll = userOrders;
  const listedPair = pairUserOrders;
  const visibleOrders = orderScope === "pair" ? pairOrders : allOrders;
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Tabs
        value={tab}
        onValueChange={setTab}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="panel-drag flex h-8 shrink-0 items-center border-b border-rule pr-1">
          <TabsList className="min-w-0 border-b-0">
            <TabsTrigger value="positions">
              Positions
              <span className="ml-1 font-mono text-[10px] text-muted">({openPositions.length})</span>
            </TabsTrigger>
            <TabsTrigger value="orders">
              Orders
              <span className="ml-1 font-mono text-[10px] text-muted">({openOrderCount})</span>
            </TabsTrigger>
            <TabsTrigger value="algos">
              Algos
              <span className="ml-1 font-mono text-[10px] text-muted">({workingAlgos.length})</span>
            </TabsTrigger>
            <TabsTrigger value="trades">Trades</TabsTrigger>
            <TabsTrigger value="funding">Funding</TabsTrigger>
          </TabsList>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex cursor-default items-baseline gap-1.5 px-1">
                  <span className="text-[11px] text-muted">uPnL</span>
                  <span className={cn("font-mono text-[11px] tabular-nums", pnlClass(totalPnl))}>
                    {formatSigned(totalPnl)}
                  </span>
                  {accountRoe != null && (
                    <span className={cn("font-mono text-[10px] tabular-nums", pnlClass(totalPnl))}>
                      {formatPct(accountRoe, 1)}
                    </span>
                  )}
                </span>
              </TooltipTrigger>
              <TooltipContent>Unrealized PnL across open positions</TooltipContent>
            </Tooltip>
            {onClose ? <PanelCloseButton onClose={onClose} /> : null}
          </div>
        </div>

        <TabsContent value="positions" className="min-h-0 flex-1 px-2">
          <ScrollArea className="h-full">
            {!liveRows.length ? (
              <Empty className="rounded-none border-0 p-4">
                <EmptyDescription className="text-[11px] text-muted">
                  {tradingEnabled
                    ? "No open positions"
                    : "Connect API key to view positions"}
                </EmptyDescription>
              </Empty>
            ) : (
              <Table className="font-mono text-[11px]">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-2.5">Market</TableHead>
                    <SortHead
                      label="Size"
                      column="size"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <SortHead
                      label="Notional"
                      column="notional"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Liq</TableHead>
                    <SortHead
                      label="uPnL"
                      column="pnl"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <SortHead
                      label="uPnL%"
                      column="roe"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                      title="Sort by unrealized PnL %"
                    />
                    <TableHead className="text-right">Funding</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedRows.map(({ p, mark, pnl, notional, roe }) => {
                    const long = isLongPosition(p);
                    const fund = n(p.funding_paid);
                    const cushion = liqCushion(p, mark);
                    const liq = n(p.liquidation_price);
                    const rowBusy = busy === `close-${p.market_index}`;
                    return (
                      <TableRow
                        key={p.market_index}
                        onClick={
                          onSymbolChange
                            ? () => {
                                if (market?.market_index !== p.market_index) onSymbolChange(p.symbol);
                              }
                            : undefined
                        }
                        title={onSymbolChange ? `Switch to ${p.symbol}` : undefined}
                        className={cn(
                          long
                            ? "shadow-[inset_2px_0_0_0_var(--color-bid)]"
                            : "shadow-[inset_2px_0_0_0_var(--color-ask)]",
                          market &&
                            p.market_index === market.market_index &&
                            "bg-elevated/35",
                          onSymbolChange && "cursor-pointer"
                        )}
                      >
                        <TableCell className="pl-2.5">
                          <span
                            className={cn(
                              long ? "text-bid" : "text-ask",
                              market?.market_index === p.market_index && "underline"
                            )}
                          >
                            {p.symbol}
                          </span>
                          <span className="ml-1.5 text-muted">
                            {p.leverage}x {p.margin_mode}
                          </span>
                        </TableCell>
                        <TableCell className={cn("text-right", long ? "text-bid" : "text-ask")}>
                          {formatSize(Math.abs(n(p.size)))}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatNotional(notional)}
                        </TableCell>
                        <TableCell className="text-right">{formatPrice(p.entry_price)}</TableCell>
                        <TableCell className="text-right">
                          {liq > 0 ? formatPrice(p.liquidation_price) : "—"}
                          {cushion != null && (
                            <span
                              className={cn(
                                "ml-1 text-[10px]",
                                cushion < 8 ? "text-ask" : "text-muted"
                              )}
                            >
                              ({cushion.toFixed(1)}%)
                            </span>
                          )}
                        </TableCell>
                        <TableCell className={cn("text-right", pnlClass(pnl))}>
                          {formatSigned(pnl)}
                        </TableCell>
                        <TableCell className={cn("text-right", roe != null ? pnlClass(roe) : "text-muted")}>
                          {roe != null ? formatPct(roe, 1) : "—"}
                        </TableCell>
                        <TableCell className={cn("text-right", pnlClass(fund))}>
                          {formatSigned(p.funding_paid)}
                        </TableCell>
                        <TableCell
                          className="pl-2 text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                type="button"
                                variant="danger"
                                size="icon"
                                disabled={!tradingEnabled || !!rowBusy}
                                onClick={() => closePosition(p)}
                                className="size-7"
                              >
                                <X strokeWidth={2.25} />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Close {p.symbol}</TooltipContent>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </ScrollArea>
        </TabsContent>

        <TabsContent value="orders" className="min-h-0 flex-1 px-2">
          <ScrollArea className="h-full">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <ToggleGroup
                type="single"
                variant="seg"
                size="sm"
                spacing={0}
                value={orderScope}
                onValueChange={(v) => {
                  if (v === "all" || v === "pair") setOrderScope(v);
                }}
              >
                <ToggleGroupItem value="all">All</ToggleGroupItem>
                <ToggleGroupItem value="pair" disabled={!market}>
                  {market?.symbol ?? "Pair"}
                </ToggleGroupItem>
              </ToggleGroup>
              <div className="ml-auto flex gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!tradingEnabled || !market || listedPair.length === 0}
                  onClick={cancelPair}
                >
                  Cancel {market?.symbol ?? "pair"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!tradingEnabled || listedAll.length === 0}
                  onClick={cancelAll}
                >
                  Cancel all
                </Button>
              </div>
            </div>
            {!visibleOrders.length ? (
              <Empty className="rounded-none border-0 p-4">
                <EmptyDescription className="text-[11px] text-muted">
                  {orderScope === "pair" && market
                    ? `No open ${market.symbol} orders`
                    : "No open orders"}
                </EmptyDescription>
              </Empty>
            ) : (
              <Table className="font-mono text-[11px]">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Market</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Remaining</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleOrders.map((o) => {
                    const algoKind = algoOrderKind(o.client_order_index);
                    return (
                    <TableRow key={o.order_index}>
                      <TableCell>
                        <span className="inline-flex items-baseline gap-1">
                          {onSymbolChange ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => onSymbolChange(o.symbol)}
                                  className={cn(
                                    "h-auto px-0 font-mono text-[11px] hover:underline",
                                    market?.market_index === o.market_index && "underline"
                                  )}
                                >
                                  {o.symbol}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Switch to {o.symbol}</TooltipContent>
                            </Tooltip>
                          ) : (
                            o.symbol
                          )}
                          {algoKind ? (
                            <span className="text-[10px] text-muted">{algoKind}</span>
                          ) : null}
                        </span>
                      </TableCell>
                      <TableCell className={o.side === "buy" ? "text-bid" : "text-ask"}>
                        {o.side}
                      </TableCell>
                      <TableCell className="text-right">{formatPrice(o.price)}</TableCell>
                      <TableCell className="text-right">{formatSize(o.remaining)}</TableCell>
                      <TableCell className="text-right">
                        {algoKind ? (
                          <span className="text-[10px] text-muted">algo</span>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={!tradingEnabled}
                            onClick={() => cancelOrder(o.market_index, o.order_index)}
                          >
                            Cancel
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </ScrollArea>
        </TabsContent>

        <TabsContent value="algos" className="mt-0 flex min-h-0 flex-1 flex-col">
          <AlgoOrdersPanel symbol={market?.symbol} tradingEnabled={tradingEnabled} />
        </TabsContent>

        <TabsContent value="trades" className="min-h-0 flex-1 px-2">
          <TradeHistoryTab
            market={market}
            tradingEnabled={tradingEnabled}
            active={tab === "trades"}
            onSymbolChange={onSymbolChange}
          />
        </TabsContent>

        <TabsContent value="funding" className="min-h-0 flex-1 px-2">
          <FundingHistoryTab
            market={market}
            tradingEnabled={tradingEnabled}
            active={tab === "funding"}
            onSymbolChange={onSymbolChange}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
