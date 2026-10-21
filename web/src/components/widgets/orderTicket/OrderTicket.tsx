import { ChevronDown } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { FieldGroup } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { notifyErr, notifyOrder } from "@/lib/notify";
import { PanelCloseButton, PanelHeader } from "@/components/desk/PanelHeader";
import { ALGOS, algoById, algoPluginById, type AlgoId } from "@/lib/algoPlugins";
import { useTradingReady } from "@/hooks/useTradingReady";
import { api, type Market } from "@/lib/api";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import {
  setAlgo as setLiveAlgo,
  useLiveAccount,
  useLiveAlgos,
  useLiveBbo,
} from "@/lib/liveData";
import { livePlannerFor, type PlannerLadderStrength } from "@/lib/plannerPlan";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const PlannerDialog = lazy(() =>
  import("@/components/widgets/planner/PlannerDialog").then((m) => ({ default: m.PlannerDialog })),
);

function PlannerDialogFallback({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Planner</DialogTitle>
          <DialogDescription>One trade from its stop.</DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  );
}
import type { OrderNoticeInput } from "@/lib/orderNotice";
import { useLimitPricePick } from "@/lib/ticketFill";
import { AlgoParams } from "./kinds/AlgoParams";
import type { ChaseParamsState } from "./kinds/ChaseParamsSheet";
import type { LadderParamsState } from "./kinds/LadderParamsSheet";
import { LimitParams } from "./kinds/LimitParams";
import { MarketParams } from "./kinds/MarketParams";
import { LeverageModal } from "./LeverageModal";
import {
  convertSizeOnUnitToggle,
  leveragePresets,
  limitCrossHint,
  loadSizeUnit,
  loadSlipPct,
  makerMinSize,
  maxOrderSize,
  minSizeHint,
  persistSizeUnit,
  persistSlipPct,
  sizeFieldOtherUnitHint,
  sizePctValue,
  snapLeverage,
  snapReduceOnlySize,
  suggestedLeverage,
  ticketBlockReason,
  ticketSizeFromInput,
  ticketWorkingPrice,
  trimQty,
  type OrderKind,
  type SizeUnit,
  type Tif,
} from "./math";
import { SizeField } from "./SizeField";

interface OrderTicketProps {
  market: Market | null;
  onOrderPlaced?: () => void;
  tradingEnabled: boolean;
  connected: boolean;
  onClose?: () => void;
}

function initialPluginStates(): Record<AlgoId, unknown> {
  const out = {} as Record<AlgoId, unknown>;
  for (const row of ALGOS) {
    const plugin = algoPluginById(row.id);
    if (plugin) out[row.id] = plugin.defaultState;
  }
  return out;
}

export function OrderTicket({
  market,
  onOrderPlaced,
  tradingEnabled,
  connected,
  onClose,
}: OrderTicketProps) {
  const feed = useTradingReady({ connected });
  const [kind, setKind] = useState<OrderKind>("algo");
  const [size, setSize] = useState("");
  const [sizeUnit, setSizeUnit] = useState<SizeUnit>(loadSizeUnit);
  const [price, setPrice] = useState("");
  const [slippagePct, setSlippagePct] = useState(loadSlipPct);
  const [reduceOnly, setReduceOnly] = useState(false);
  const [tif, setTif] = useState<Tif>("gtt");
  const [algo, setAlgo] = useState<AlgoId>("chase-iceberg");
  const [pluginStates, setPluginStates] = useState(initialPluginStates);
  const [leverage, setLeverage] = useState("5");
  const [levOpen, setLevOpen] = useState(false);
  const [levDraft, setLevDraft] = useState("");
  const [busy, setBusy] = useState<"buy" | "sell" | "ticket" | null>(null);
  const [syncedSymbol, setSyncedSymbol] = useState<string | null>(null);
  const bookPick = useLimitPricePick();
  const lastBookPickSeq = useRef(0);
  const bbo = useLiveBbo();
  const account = useLiveAccount();
  const algoBook = useLiveAlgos();
  const [plannerOpen, setPlannerOpen] = useState(false);
  const runningPlanner = livePlannerFor(algoBook, market?.market_index);
  const tradeAvailable =
    parseFloat(account?.trade_available ?? account?.available ?? "0") || 0;
  const signedPos =
    parseFloat(
      account?.positions.find((p) => p.market_index === market?.market_index)?.size ?? "0"
    ) || 0;

  useEffect(() => {
    if (!bookPick || bookPick.seq === lastBookPickSeq.current) return;
    lastBookPickSeq.current = bookPick.seq;
    setPrice(bookPick.price);
    setKind("limit");
  }, [bookPick]);

  const loading = busy != null;
  const plugin = algoPluginById(algo);
  const singleAction = kind === "algo" && !!plugin?.singleAction;
  const pluginState = pluginStates[algo];

  if (market && market.symbol !== syncedSymbol) {
    setSyncedSymbol(market.symbol);
    setSize("");
    setPrice("");
    setPluginStates((prev) => {
      const next = { ...prev };
      for (const row of ALGOS) {
        const p = algoPluginById(row.id);
        if (p) next[row.id] = p.resetState(prev[row.id]);
      }
      return next;
    });
    setLeverage(suggestedLeverage(market, account?.positions));
  }

  if (!market) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PanelHeader title="Order" onClose={onClose} />
        <Empty className="rounded-none border-0">
          <EmptyHeader>
            <EmptyTitle>No market selected</EmptyTitle>
            <EmptyDescription>Pick a pair from the header or favorites</EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  const submit = async (
    fn: () => Promise<unknown>,
    notice: OrderNoticeInput,
    side?: "buy" | "sell"
  ) => {
    if (!tradingEnabled) {
      notifyErr("Trading not configured. Add API credentials to backend .env");
      return;
    }
    setBusy(side ?? "ticket");
    try {
      await fn();
      notifyOrder({ ...notice, side: side ?? notice.side });
      onOrderPlaced?.();
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Order failed");
    } finally {
      setBusy(null);
    }
  };

  const presets = leveragePresets(market);
  const maxLev = presets[presets.length - 1] ?? market.max_leverage ?? 20;
  const lev = presets.includes(parseInt(leverage, 10)) ? parseInt(leverage, 10) : maxLev;

  const applyLeverage = (value: string) => {
    const x = snapLeverage(presets, value);
    if (x == null) {
      notifyErr("Enter a leverage");
      return;
    }
    setLeverage(String(x));
    setLevDraft(String(x));
    setLevOpen(false);
    if (!tradingEnabled) return;
    if (x !== lev) {
      submit(
        () => api.updateLeverage(market.market_index, x, true),
        { kind: "leverage", note: `${x}x`, symbol: market.symbol }
      );
    }
  };

  const bid = parseFloat(bbo.bid ?? "");
  const ask = parseFloat(bbo.ask ?? "");
  const mid = bid > 0 && ask > 0 ? (bid + ask) / 2 : null;
  const spot =
    mid ??
    (bid > 0 ? bid : null) ??
    (ask > 0 ? ask : null) ??
    (market.last_trade_price && market.last_trade_price > 0 ? market.last_trade_price : null);
  const slipFrac = Math.max(0, (parseFloat(slippagePct) || 0) / 100);
  const worstBuy = spot != null ? spot * (1 + slipFrac) : null;
  const worstSell = spot != null ? spot * (1 - slipFrac) : null;
  const decimals = market.size_decimals ?? 4;
  const priceDecimals = market.price_decimals ?? 4;
  const priceNum = parseDecimal(price) ?? 0;
  const workingPrice = ticketWorkingPrice({ kind, priceNum, spot });
  const canUseUsd = workingPrice != null && workingPrice > 0;
  const sizeNum = ticketSizeFromInput(size, sizeUnit, workingPrice, decimals);
  const absPos = Math.abs(signedPos);
  const orderSizeNum = reduceOnly
    ? snapReduceOnlySize(sizeNum, absPos, decimals)
    : sizeNum;
  const limitPx = kind === "limit" && priceNum > 0 ? priceNum : spot;
  const crossHint =
    kind === "limit" ? limitCrossHint({ price: priceNum, bid, ask, tif, priceDecimals }) : null;
  // Planner E16, EL6: a ticket set to Chase or Ladder opens Planner with that entry from its fields.
  const plannerFromTicket = (() => {
    if (kind !== "algo" || (algo !== "chase-iceberg" && algo !== "ladder")) return undefined;
    const qty = trimQty(sizeNum, decimals);
    if (algo === "ladder") {
      const l = pluginState as LadderParamsState;
      // The ticket's skew is only in play under Advanced; its window and variance stay behind.
      const strength: PlannerLadderStrength =
        l.advanced && (l.sizeSkew === "low" || l.sizeSkew === "high") ? l.sizeSkew : "even";
      return {
        entryType: "ladder" as const,
        entryLadder: { from: l.priceFrom, to: l.priceTo, rungs: l.orders, strength },
        ...(qty ? { sizeMode: "size" as const, size: qty } : {}),
      };
    }
    const c = pluginState as ChaseParamsState;
    return {
      entryType: "chase" as const,
      entryChase: {
        low: c.chaseFloor,
        high: c.chaseCeiling,
        offsetBps: c.offsetBps || "4",
        clip: c.displayQty,
      },
      ...(qty ? { sizeMode: "size" as const, size: qty } : {}),
    };
  })();
  const pxForSide = (s: "buy" | "sell") => {
    if (kind === "limit" && priceNum > 0) return priceNum;
    const worst = s === "buy" ? worstBuy : worstSell;
    if (kind === "market" && worst != null && worst > 0) return worst;
    if (s === "buy") return ask > 0 ? ask : spot;
    return bid > 0 ? bid : spot;
  };
  const maxBuy = maxOrderSize({
    available: tradeAvailable,
    leverage: lev,
    price: pxForSide("buy"),
    signedPos,
    side: "buy",
    reduceOnly,
  });
  const maxSell = maxOrderSize({
    available: tradeAvailable,
    leverage: lev,
    price: pxForSide("sell"),
    signedPos,
    side: "sell",
    reduceOnly,
  });
  const maxSize = Math.max(maxBuy, maxSell);
  const worst = spot;
  const isMaker = kind === "limit" && tif !== "ioc";
  const minSz = makerMinSize(
    market.min_base_amount ?? 0,
    market.min_quote_amount ?? 0,
    limitPx,
    decimals
  );
  const sizeMin = minSizeHint(minSz, decimals, orderSizeNum);
  const otherUnitHint = sizeFieldOtherUnitHint({
    raw: size,
    unit: sizeUnit,
    symbol: market.symbol,
    price: workingPrice,
    decimals,
    sizeNum: orderSizeNum,
  });

  const setSizePct = (pct: number) => {
    if (maxSize <= 0) return;
    setSize(sizePctValue(pct, maxSize, sizeUnit, workingPrice, decimals));
  };

  const toggleSizeUnit = () => {
    const next: SizeUnit = sizeUnit === "base" ? "usd" : "base";
    if (next === "usd" && !canUseUsd) return;
    setSize(convertSizeOnUnitToggle(size, sizeUnit, next, workingPrice, decimals));
    setSizeUnit(next);
    persistSizeUnit(next);
  };

  const onSlipChange = (raw: string) => {
    setSlippagePct(raw);
    persistSlipPct(raw);
  };

  const algoBlockCtx = {
    sizeNum: orderSizeNum,
    decimals,
    minSz,
    symbol: market.symbol,
    spot,
    slipFrac,
    reduceOnly,
    priceDecimals: market.price_decimals,
    minBase: market.min_base_amount ?? 0,
    minQuote: market.min_quote_amount ?? 0,
  };
  const algoBlocked =
    kind === "algo" && plugin
      ? plugin.blockReason(pluginState, algoBlockCtx)
      : null;

  const blockOpts = {
    tradingEnabled,
    feedReady: feed.ready,
    feedReason: feed.reason,
    sizeNum: orderSizeNum,
    sizeRaw: size,
    sizeUnit,
    workingPrice,
    symbol: market.symbol,
    decimals,
    kind,
    price,
    isMaker,
    minSz,
    algoBlocked,
  };
  const sharedBlocked = ticketBlockReason(blockOpts);
  const buyBlocked = ticketBlockReason({ ...blockOpts, maxSize: maxBuy });
  const sellBlocked = ticketBlockReason({
    ...blockOpts,
    maxSize: maxSell,
    sellBid: bid > 0 ? bid : null,
  });
  const actionBlocked = singleAction
    ? ticketBlockReason({ ...blockOpts, maxSize })
    : null;

  const orderCtaLabel = (side: "buy" | "sell") => {
    if (kind === "algo" && plugin) return plugin.cta(side);
    return side === "buy" ? "Buy" : "Sell";
  };

  const send = async (orderSide: "buy" | "sell") => {
    const blocked = singleAction
      ? actionBlocked
      : orderSide === "buy"
        ? buyBlocked
        : sellBlocked;
    if (blocked || loading) return;
    const qSize = trimQty(orderSizeNum, decimals) || (canonicalDecimal(size) ?? size);
    const qPrice =
      priceNum > 0 ? trimQty(priceNum, priceDecimals) || canonicalDecimal(price) || price : price;
    if (kind === "market") {
      await submit(
        () =>
          api.placeMarketOrder({
            market_index: market.market_index,
            side: orderSide,
            size: qSize,
            slippage: slipFrac || 0.01,
            reduce_only: reduceOnly,
          }),
        { kind: "market", size: qSize, symbol: market.symbol },
        orderSide
      );
      return;
    }
    if (kind === "limit") {
      await submit(
        () =>
          api.placeLimitOrder({
            market_index: market.market_index,
            side: orderSide,
            size: qSize,
            price: qPrice,
            time_in_force: tif,
            reduce_only: reduceOnly,
          }),
        { kind: "limit", size: qSize, symbol: market.symbol, price: qPrice },
        orderSide
      );
      return;
    }
    if (kind === "algo" && plugin) {
      setBusy(orderSide);
      try {
        const result = await plugin.submit(pluginState, {
          market,
          side: orderSide,
          qSize,
          sizeNum: orderSizeNum,
          decimals,
          reduceOnly,
          spot,
          slipFrac,
        });
        if (result.setLiveBook && result.book) setLiveAlgo(result.book);
        notifyOrder(result.notice);
        onOrderPlaced?.();
      } catch (e) {
        notifyErr(e instanceof Error ? e.message : "Order failed");
      } finally {
        setBusy(null);
      }
    }
  };

  return (
    <div className="panel-drag flex h-full min-h-0 flex-col overflow-hidden">
      <form
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <Tabs
          value={kind}
          onValueChange={(v) => setKind(v as OrderKind)}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="flex shrink-0 flex-col gap-2 border-b border-border p-1.5">
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 min-w-0 flex-1"
                onClick={() => {
                  setLevDraft(String(lev));
                  setLevOpen(true);
                }}
              >
                <span className="font-mono tabular-nums">{lev}x</span>
              </Button>
              {!singleAction ? (
                <Button
                  type="button"
                  variant={reduceOnly ? "secondary" : "outline"}
                  size="sm"
                  className="h-7 min-w-0 flex-1"
                  aria-pressed={reduceOnly}
                  title="Reduces position only — will not open or flip"
                  onClick={() => setReduceOnly((v) => !v)}
                >
                  Close
                </Button>
              ) : null}
              {onClose ? <PanelCloseButton onClose={onClose} /> : null}
            </div>
            <div className="flex items-center gap-1">
              <ToggleGroup
                type="single"
                variant="ghost"
                size="sm"
                spacing={0}
                value={kind === "algo" ? "" : kind}
                onValueChange={(v) => {
                  if (v === "market" || v === "limit") setKind(v);
                }}
                aria-label="Order type"
              >
                <ToggleGroupItem value="market" className="h-7 px-2.5">
                  Market
                </ToggleGroupItem>
                <ToggleGroupItem value="limit" className="h-7 px-2.5">
                  Limit
                </ToggleGroupItem>
              </ToggleGroup>
              <div className="min-w-0 flex-1" />
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="h-7 shrink-0"
                  >
                    {kind === "algo" ? algoById(algo).label : "Algo"}
                    <ChevronDown data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-36">
                  <DropdownMenuGroup>
                    {ALGOS.map((a) => (
                      <DropdownMenuItem
                        key={a.id}
                        onSelect={() => {
                          setAlgo(a.id);
                          setKind("algo");
                        }}
                      >
                        {a.label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={!tradingEnabled}
                    onSelect={() => setPlannerOpen(true)}
                  >
                    {runningPlanner ? "Re-plan…" : signedPos !== 0 ? "Plan Position…" : "Planner…"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <FieldGroup className="gap-3 px-2.5 py-2">
              <SizeField
                symbol={market.symbol}
                size={size}
                sizeNum={orderSizeNum}
                maxSize={maxSize}
                maxTitle={
                  singleAction
                    ? "Max inventory cap at this leverage"
                    : reduceOnly
                    ? "Position size"
                    : "Available at this leverage. Opposite side includes close + flip."
                }
                decimals={decimals}
                sizeUnit={sizeUnit}
                workingPrice={workingPrice}
                otherUnitHint={otherUnitHint}
                canUseUsd={canUseUsd}
                label={singleAction ? "Cap" : "Size"}
                minHint={sizeMin?.text}
                minHintWarn={sizeMin?.warn}
                onSizeChange={setSize}
                onSizePct={setSizePct}
                onUnitToggle={toggleSizeUnit}
              />

              <TabsContent value="market" className="mt-0">
                <MarketParams slippagePct={slippagePct} worst={worst} onSlipChange={onSlipChange} />
              </TabsContent>

              <TabsContent value="limit" className="mt-0">
                <LimitParams
                  price={price}
                  bid={bid}
                  ask={ask}
                  mid={mid}
                  priceDecimals={priceDecimals}
                  tif={tif}
                  crossHint={crossHint?.text ?? null}
                  onPriceChange={setPrice}
                  onTifChange={setTif}
                />
              </TabsContent>

              <TabsContent value="algo" className="mt-0">
                <AlgoParams
                  algo={algo}
                  market={market}
                  bookMid={mid}
                  sizeNum={orderSizeNum}
                  pluginState={pluginState}
                  onPluginStateChange={(state) =>
                    setPluginStates((prev) => ({ ...prev, [algo]: state }))
                  }
                />
              </TabsContent>
            </FieldGroup>
          </ScrollArea>
        </Tabs>

        <div className="flex shrink-0 flex-col gap-2 border-t border-border px-2.5 py-2">
          {sharedBlocked && feed.ready === false ? (
            <Alert variant="warn">{sharedBlocked}</Alert>
          ) : sharedBlocked && !tradingEnabled ? (
            <Alert>{sharedBlocked}</Alert>
          ) : sharedBlocked ? (
            <p className="text-center text-base text-muted-foreground">{sharedBlocked}</p>
          ) : null}
          {singleAction ? (
            <Button
              type="button"
              variant="outline"
              className="h-8 w-full truncate"
              disabled={loading || !!sharedBlocked || !!actionBlocked}
              title={sharedBlocked ?? actionBlocked ?? undefined}
              onClick={() => void send("buy")}
            >
              {busy ? "Sending…" : sharedBlocked || actionBlocked || orderCtaLabel("buy")}
            </Button>
          ) : (
            <div className="grid grid-cols-2 gap-1">
              <Button
                type="button"
                variant="buy"
                className="h-8 truncate"
                disabled={loading || !!buyBlocked}
                title={buyBlocked ?? undefined}
                onClick={() => void send("buy")}
              >
                {busy === "buy"
                  ? "Sending…"
                  : !sharedBlocked && buyBlocked
                    ? buyBlocked
                    : orderCtaLabel("buy")}
              </Button>
              <Button
                type="button"
                variant="sell"
                className="h-8 truncate"
                disabled={loading || !!sellBlocked}
                title={sellBlocked ?? undefined}
                onClick={() => void send("sell")}
              >
                {busy === "sell"
                  ? "Sending…"
                  : !sharedBlocked && sellBlocked
                    ? sellBlocked
                    : orderCtaLabel("sell")}
              </Button>
            </div>
          )}
        </div>
      </form>

      <LeverageModal
        open={levOpen}
        symbol={market.symbol}
        lev={lev}
        presets={presets}
        maxLev={maxLev}
        draft={levDraft}
        loading={loading}
        tradingEnabled={tradingEnabled}
        onDraftChange={setLevDraft}
        onClose={() => setLevOpen(false)}
        onApply={applyLeverage}
      />
      {plannerOpen ? (
        <Suspense fallback={<PlannerDialogFallback onOpenChange={setPlannerOpen} />}>
          <PlannerDialog
            open={plannerOpen}
            onOpenChange={setPlannerOpen}
            market={market}
            mode={runningPlanner || signedPos !== 0 ? "attach" : "enter"}
            side={signedPos < 0 ? "sell" : "buy"}
            running={runningPlanner}
            initial={plannerFromTicket}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
