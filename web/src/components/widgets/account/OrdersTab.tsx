import { useMemo, useState } from "react";
import { notifyErr, notifyOk } from "@/lib/notify";
import { OrderRemainingEditor } from "@/components/widgets/OrderRemainingEditor";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableName, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ScopeToggle } from "@/components/widgets/ListControls";
import { api, type Market, type OpenOrder } from "@/lib/api";
import { algoOrderKind, isAlgoClientOrder } from "@/lib/algos";
import { protectOrderLabel, stopTakeKind } from "@/lib/positionsTable";
import { cn, formatSize } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";

function orderQtyEditable(order: OpenOrder): boolean {
  if (isAlgoClientOrder(order.client_order_index)) return false;
  if (stopTakeKind(order.order_type)) return false;
  return parseFloat(order.remaining) > 0;
}

interface OrdersTabProps {
  market: Market | null;
  markets: Market[];
  orders: OpenOrder[];
  tradingEnabled: boolean;
  feed: { ready: boolean; reason?: string | null };
  busy: string | null;
  setBusy: (key: string | null) => void;
  onCancel: (marketIndex: number, orderIndex: string | number) => Promise<void>;
  onSymbolChange?: (symbol: string) => void;
}

/** The Orders tab: every working order, bulk side cancel of Tickets, and in-place Amend of size. */
export function OrdersTab({
  market,
  markets,
  orders: allOrders,
  tradingEnabled,
  feed,
  busy,
  setBusy,
  onCancel: cancelOrder,
  onSymbolChange,
}: OrdersTabProps) {
  const [orderScope, setOrderScope] = useState<"all" | "pair">("all");
  const [editingOrder, setEditingOrder] = useState<string | number | null>(null);

  const marketByIndex = useMemo(
    () => new Map(markets.map((m) => [m.market_index, m])),
    [markets]
  );

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

  return (
          <ScrollArea className="h-full">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <ScopeToggle scope={orderScope} onScopeChange={setOrderScope} pair={market?.symbol} />
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
  );
}
