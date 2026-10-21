import { lazy, Suspense, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { notifyErr, notifyOk, notifyWarn } from "@/lib/notify";
import { OverflowMenu } from "@/components/desk/OverflowMenu";
import { PanelCloseButton } from "@/components/desk/PanelHeader";
import { PositionProtectPopover } from "@/components/widgets/PositionProtectPopover";
import { PositionPlanButton } from "@/components/widgets/planner/PositionPlanButton";
import { livePlannerFor } from "@/lib/plannerPlan";
import { liveTrailsFor } from "@/lib/trail";
import { AssetsTab } from "@/components/widgets/account/AssetsTab";
import { AlgoOrdersPanel } from "@/components/widgets/AlgoOrdersPanel";
import { OrderRemainingEditor } from "@/components/widgets/OrderRemainingEditor";
import { Button } from "@/components/ui/button";
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
  type HideBelow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useToolbarFold } from "@/hooks/useToolbarFold";
import { useTradingReady } from "@/hooks/useTradingReady";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { api, isLongPosition, type Market, type OpenOrder, type Position } from "@/lib/api";
import { algoBlotter, algoOrderKind, isAlgoClientOrder } from "@/lib/algos";
import { setAlgo, useJournalOpen, useLiveAccount, useLiveAlgos, useLiveBbo } from "@/lib/liveData";
import {
  nextPosSort,
  positionNotional,
  positionsForClose,
  protectOrderLabel,
  sortPositionRows,
  stopTakeKind,
  type CloseFilter,
  type PosSort,
  type PosSortKey,
  realizedFor,
  realizedTitle,
} from "@/lib/positionsTable";
import { cn, formatPctAbs, formatSigned, formatSize, formatUsd } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";

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

function orderQtyEditable(order: OpenOrder): boolean {
  if (isAlgoClientOrder(order.client_order_index)) return false;
  if (stopTakeKind(order.order_type)) return false;
  return parseFloat(order.remaining) > 0;
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

function pnlClass(value: number) {
  if (value > 0) return "text-bid";
  if (value < 0) return "text-ask";
  return "text-muted-foreground";
}

function SortHead({
  label,
  column,
  sort,
  onSort,
  title,
  hideBelow,
}: {
  label: string;
  column: PosSortKey;
  sort: PosSort;
  onSort: (key: PosSortKey) => void;
  title?: string;
  hideBelow?: HideBelow;
}) {
  const active = sort.key === column;
  return (
    <TableHead hideBelow={hideBelow} className="text-right">
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
  const [orderScope, setOrderScope] = useState<"all" | "pair">("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [editingOrder, setEditingOrder] = useState<string | number | null>(null);
  const [posSort, setPosSort] = useState<PosSort>({ key: "notional", dir: "desc" });

  const marketByIndex = useMemo(
    () => new Map(markets.map((m) => [m.market_index, m])),
    [markets]
  );

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

  const amendRemaining = async (order: OpenOrder, size: string) => {
    if (!tradingEnabled) {
      notifyErr("Trading not configured");
      return;
    }
    const key = `amend-${order.order_index}`;
    if (busy != null) return;
    setBusy(key);
    try {
      await api.amendOrder(order.market_index, order.order_index, order.price, size);
      notifyOk("Order amended");
      setEditingOrder(null);
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Amend failed");
    } finally {
      setBusy(null);
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

  const cancelTickets = async (side: "buy" | "sell") => {
    if (!tradingEnabled) {
      notifyErr("Trading not configured");
      return;
    }
    if (!feed.ready) {
      notifyErr(feed.reason ?? "Feed not ready");
      return;
    }
    const marketIndex = orderScope === "pair" ? market?.market_index : null;
    if (orderScope === "pair" && marketIndex == null) return;
    const noun = side === "buy" ? "bids" : "asks";
    const key = `cancel-${side}`;
    setBusy(key);
    try {
      const out = await api.cancelTickets(side, marketIndex);
      const n = out.cancelled;
      if (out.error) {
        notifyErr(n > 0 ? `Cancelled ${n} ${noun}; ${out.error}` : out.error);
        return;
      }
      if (n === 0) {
        notifyErr(side === "buy" ? "No buy Tickets" : "No sell Tickets");
        return;
      }
      notifyOk(`Cancelled ${n} ${noun}`);
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Cancel failed");
    } finally {
      setBusy(null);
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
  const scopedTickets = orderScope === "pair" ? listedPair : listedAll;
  const bidTickets = scopedTickets.filter((o) => o.side === "buy").length;
  const askTickets = scopedTickets.filter((o) => o.side === "sell").length;
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
  const winners = positionsForClose(liveRows, "winners");
  const losers = positionsForClose(liveRows, "losers");
  const closeBlocked = !tradingEnabled || !feed.ready || busy != null;
  const closeChoices = [
    { filter: "winners", label: "W", noun: "winners", menu: "Close winners", count: winners.length, className: "text-bid hover:text-bid" },
    { filter: "losers", label: "L", noun: "losers", menu: "Close losers", count: losers.length, className: "text-ask hover:text-ask" },
    { filter: "all", label: "All", noun: "positions", menu: "Close all", count: liveRows.length, className: undefined },
  ] as const;

  // A narrow panel folds the close chips into `…` first, then the uPnL readout.
  const barRef = useRef<HTMLDivElement>(null);
  const folded = useToolbarFold(
    barRef,
    2,
    `${winners.length}:${losers.length}:${liveRows.length}:${formatSigned(totalPnl).length}`
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
            {folded < 2 ? (
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
                {folded > 1 ? (
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
              <Table>
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
                      hideBelow="xl"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <TableHead hideBelow="lg" className="text-right">Entry</TableHead>
                    <TableHead hideBelow="2xl" className="text-right">Liq</TableHead>
                    <SortHead
                      label="uPnL"
                      column="pnl"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <TableHead
                      hideBelow="lg"
                      className="text-right"
                      title="What this Position has closed since it opened, less fees. From the Journal, a few seconds behind a fill."
                    >
                      Realized
                    </TableHead>
                    <TableHead hideBelow="2xl" className="text-right">Funding</TableHead>
                    <TableHead hideBelow="sm" className="text-right">TP/SL</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedRows.map(({ p, mark, pnl, notional, roe }) => {
                    const long = isLongPosition(p);
                    const fund = n(p.funding_paid);
                    const realized = realizedFor(p, journalOpen);
                    const realizedNum = realized ? n(realized.realized) : 0;
                    const cushion = liqCushion(p, mark);
                    const liq = n(p.liquidation_price);
                    const m = markets.find((x) => x.market_index === p.market_index) ?? market;
                    const planner = livePlannerFor(algoBook, p.market_index);
                    const trails = liveTrailsFor(algoBook, p.market_index);
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
                        accent={long ? "bid" : "ask"}
                        className={cn(
                          market &&
                            p.market_index === market.market_index &&
                            "bg-elevated/35",
                          onSymbolChange && "cursor-pointer"
                        )}
                      >
                        <TableCell className="pl-2.5">
                          <TableName
                            className={cn(
                              long ? "text-bid" : "text-ask",
                              market?.market_index === p.market_index && "underline"
                            )}
                          >
                            {p.symbol}
                          </TableName>
                          <span className="ml-1.5 text-muted-foreground @max-lg/table:hidden">
                            {p.leverage}x {p.margin_mode}
                          </span>
                        </TableCell>
                        <TableCell className={cn("text-right", long ? "text-bid" : "text-ask")}>
                          {formatSize(Math.abs(n(p.size)))}
                        </TableCell>
                        <TableCell hideBelow="xl" className="text-right">
                          {notional > 0 ? formatUsd(notional) : "—"}
                        </TableCell>
                        <TableCell hideBelow="lg" className="text-right">
                          {marketPrice(p.entry_price, p.symbol)}
                        </TableCell>
                        <TableCell hideBelow="2xl" className="text-right">
                          {liq > 0 ? marketPrice(p.liquidation_price, p.symbol) : "—"}
                          {cushion != null && (
                            <span
                              className={cn(
                                "ml-1 text-xs",
                                cushion < 8 ? "text-ask" : "text-muted-foreground"
                              )}
                            >
                              ({formatPctAbs(cushion)})
                            </span>
                          )}
                        </TableCell>
                        <TableCell className={cn("text-right font-medium", pnlClass(pnl))}>
                          {formatSigned(pnl)}
                          {roe != null && (
                            <span className="ml-1 text-xs font-normal">({formatPctAbs(roe)})</span>
                          )}
                        </TableCell>
                        <TableCell
                          hideBelow="lg"
                          className={cn("text-right", realized ? pnlClass(realizedNum) : "text-muted-foreground")}
                          title={realized ? realizedTitle(realized, (x) => formatSigned(x)) : "Not in the Journal yet"}
                        >
                          {realized ? (
                            <>
                              {realized.partial ? <span className="text-muted-foreground">~</span> : null}
                              {formatSigned(realizedNum)}
                            </>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell hideBelow="2xl" className={cn("text-right", pnlClass(fund))}>
                          {formatSigned(p.funding_paid)}
                        </TableCell>
                        <TableCell
                          hideBelow="sm"
                          className="text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="inline-flex items-center justify-end gap-1.5">
                            <PositionProtectPopover
                              lockedBy={planner ? "Planner" : null}
                              position={p}
                              mark={mark}
                              sizeDecimals={m?.size_decimals ?? 4}
                              priceDecimals={m?.price_decimals ?? 4}
                              tradingEnabled={tradingEnabled && feed.ready}
                              busy={busy != null}
                              orders={allOrders}
                              onPlace={async (body) => {
                                const ok = await run(
                                  `protect-${p.market_index}`,
                                  () => api.placeStopTake(body),
                                  `${p.symbol} stop / take profit placed`
                                );
                                if (!ok) throw new Error("not placed");
                              }}
                              onCancel={async (orderIndex) => {
                                await cancelOrder(p.market_index, orderIndex);
                              }}
                              trails={trails}
                              onStartTrail={async (body) => {
                                const ok = await run(
                                  `trail-${p.market_index}`,
                                  async () => setAlgo(await api.algoStart("trail", body)),
                                  `${p.symbol} ${body.kind === "tp" ? "Trail Take Profit" : "Trail Stop"} started`
                                );
                                if (!ok) throw new Error("not started");
                              }}
                            />
                            <PositionPlanButton
                              position={p}
                              market={m ?? null}
                              running={planner}
                              disabled={!tradingEnabled || !feed.ready || busy != null}
                            />
                          </div>
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
                                disabled={!tradingEnabled || busy != null}
                                onClick={() => closePosition(p)}
                                className="size-6"
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

        <TabsContent value="assets" className="min-h-0 flex-1 px-2">
          <AssetsTab
            assets={account?.assets ?? []}
            markets={markets}
            tradingEnabled={tradingEnabled}
            onSymbolChange={onSymbolChange}
          />
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
                  className="text-bid hover:text-bid"
                  title="Cancel buy Tickets"
                  disabled={!tradingEnabled || busy != null || bidTickets === 0}
                  onClick={() => void cancelTickets("buy")}
                >
                  Bids {bidTickets}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-ask hover:text-ask"
                  title="Cancel sell Tickets"
                  disabled={!tradingEnabled || busy != null || askTickets === 0}
                  onClick={() => void cancelTickets("sell")}
                >
                  Asks {askTickets}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!tradingEnabled || busy != null || !market || listedPair.length === 0}
                  onClick={cancelPair}
                >
                  Cancel {market?.symbol ?? "pair"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!tradingEnabled || busy != null || listedAll.length === 0}
                  onClick={cancelAll}
                >
                  Cancel all
                </Button>
              </div>
            </div>
            {!visibleOrders.length ? (
              <Empty className="rounded-none border-0 p-4">
                <EmptyDescription>
                  {orderScope === "pair" && market
                    ? `No open ${market.symbol} orders`
                    : "No open orders"}
                </EmptyDescription>
              </Empty>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Market</TableHead>
                    <TableHead hideBelow="sm">Side</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Remaining</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleOrders.map((o) => {
                    const algoKind = algoOrderKind(o.client_order_index, {
                      reduceOnly: o.reduce_only,
                    });
                    const sltp = !algoKind ? stopTakeKind(o.order_type) : null;
                    return (
                    <TableRow key={o.order_index} accent={o.side === "buy" ? "bid" : "ask"}>
                      <TableCell className="pl-2.5">
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
                                    "h-auto px-0 hover:underline",
                                    market?.market_index === o.market_index && "underline"
                                  )}
                                >
                                  <TableName>{o.symbol}</TableName>
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Switch to {o.symbol}</TooltipContent>
                            </Tooltip>
                          ) : (
                            <TableName>{o.symbol}</TableName>
                          )}
                          {algoKind ? (
                            <span className="text-xs text-muted-foreground">{algoKind}</span>
                          ) : sltp ? (
                            <span className="text-xs text-muted-foreground">
                              {protectOrderLabel(o.order_type, o.trigger_price)}
                            </span>
                          ) : null}
                        </span>
                      </TableCell>
                      <TableCell hideBelow="sm" className={o.side === "buy" ? "text-bid" : "text-ask"}>
                        {o.side}
                      </TableCell>
                      <TableCell className="text-right">
                        {marketPrice(
                          sltp && parseFloat(o.trigger_price ?? "") > 0
                            ? o.trigger_price
                            : o.price,
                          o.symbol
                        )}
                      </TableCell>
                      <TableCell className="relative text-right">
                        {orderQtyEditable(o) && tradingEnabled ? (
                          <button
                            type="button"
                            className={cn(
                              "cursor-text font-mono tabular-nums underline decoration-dotted underline-offset-2 hover:decoration-solid",
                              editingOrder === o.order_index && "invisible"
                            )}
                            disabled={busy != null}
                            title="Edit remaining size"
                            onClick={() => setEditingOrder(o.order_index)}
                          >
                            {formatSize(o.remaining)}
                          </button>
                        ) : (
                          <span>{formatSize(o.remaining)}</span>
                        )}
                        {orderQtyEditable(o) && tradingEnabled && editingOrder === o.order_index ? (
                          <OrderRemainingEditor
                            initial={formatSize(o.remaining)}
                            decimals={marketByIndex.get(o.market_index)?.size_decimals ?? 4}
                            disabled={busy != null}
                            className="absolute top-1/2 right-2 z-10 h-6 w-24 -translate-y-1/2 rounded-md border border-ring bg-popover px-1.5 text-foreground shadow-md focus-visible:border-ring focus-visible:ring-1"
                            onCancel={() => setEditingOrder(null)}
                            onCommit={(size) => void amendRemaining(o, size)}
                          />
                        ) : null}
                      </TableCell>
                      <TableCell className="text-right">
                        {algoKind ? (
                          <span className="text-xs text-muted-foreground">algo</span>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6"
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
