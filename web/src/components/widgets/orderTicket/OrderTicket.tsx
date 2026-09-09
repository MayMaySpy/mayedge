import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { notifyErr, notifyOrder } from "@/lib/notify";
import { PanelCloseButton, PanelHeader } from "@/components/desk/PanelHeader";
import { algoById, algoReasonLabel, ALGOS, twapDurationSeconds, twapFreqSeconds, twapSlipFromMaxPrice, type AlgoId, type TwapStyle } from "@/lib/algos";
import { useTradingReady } from "@/hooks/useTradingReady";
import { api, type Market } from "@/lib/api";
import { setAlgo as setLiveAlgo, useLiveAccount, useLiveBbo } from "@/lib/liveData";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import type { OrderNoticeInput } from "@/lib/orderNotice";
import { useLimitPricePick } from "@/lib/ticketFill";
import { AlgoParams } from "./kinds/AlgoParams";
import { LimitParams } from "./kinds/LimitParams";
import { MarketParams } from "./kinds/MarketParams";
import { LeverageModal } from "./LeverageModal";
import {
  leveragePresets,
  loadSlipPct,
  makerMinSize,
  maxOrderSize,
  minSizeHint,
  ORDER_KINDS,
  orderCta,
  persistSlipPct,
  snapLeverage,
  suggestedLeverage,
  ticketBlockReason,
  trimQty,
  type OrderKind,
} from "./math";
import { SizeField } from "./SizeField";
import { cn } from "@/lib/utils";

interface OrderTicketProps {
  market: Market | null;
  onOrderPlaced?: () => void;
  tradingEnabled: boolean;
  connected: boolean;
  onClose?: () => void;
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
  const [price, setPrice] = useState("");
  const [slippagePct, setSlippagePct] = useState(loadSlipPct);
  const [reduceOnly, setReduceOnly] = useState(false);
  const [tif, setTif] = useState("gtt");
  const [algo, setAlgo] = useState<AlgoId>("chase-iceberg");
  const [twapHours, setTwapHours] = useState("");
  const [twapMinutes, setTwapMinutes] = useState("30");
  const [twapMaxPrice, setTwapMaxPrice] = useState("");
  const [twapAdvanced, setTwapAdvanced] = useState(false);
  const [twapRandomize, setTwapRandomize] = useState(true);
  const [twapStyle, setTwapStyle] = useState<TwapStyle>("neutral");
  const [twapFreq, setTwapFreq] = useState("5");
  const [twapIndexPct, setTwapIndexPct] = useState("");
  const [displayQty, setDisplayQty] = useState("");
  const [offsetBps, setOffsetBps] = useState("4");
  const [chaseFloor, setChaseFloor] = useState("");
  const [chaseCeiling, setChaseCeiling] = useState("");
  const [leverage, setLeverage] = useState("5");
  const [levOpen, setLevOpen] = useState(false);
  const [levDraft, setLevDraft] = useState("");
  const [busy, setBusy] = useState<"buy" | "sell" | "ticket" | null>(null);
  const [syncedSymbol, setSyncedSymbol] = useState<string | null>(null);
  const bookPick = useLimitPricePick();
  const lastBookPickSeq = useRef(0);
  const bbo = useLiveBbo();
  const account = useLiveAccount();
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

  if (market && market.symbol !== syncedSymbol) {
    setSyncedSymbol(market.symbol);
    setSize("");
    setPrice("");
    setChaseFloor("");
    setChaseCeiling("");
    setDisplayQty("");
    setLeverage(suggestedLeverage(market, account?.positions));
  }

  if (!market) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PanelHeader title="Order" onClose={onClose} />
        <Empty className="rounded-none border-0">
          <EmptyHeader>
            <EmptyTitle className="text-sm text-text">No market selected</EmptyTitle>
            <EmptyDescription className="text-[11px] text-muted">
              Pick a pair from the chart or favorites
            </EmptyDescription>
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
  const sizeNum = parseDecimal(size) ?? 0;
  const decimals = market.size_decimals ?? 4;
  const priceDecimals = market.price_decimals ?? 4;
  const twapSec = twapDurationSeconds(twapHours, twapMinutes);
  const priceNum = parseDecimal(price) ?? 0;
  const limitPx = kind === "limit" && priceNum > 0 ? priceNum : spot;
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
  const minSz = makerMinSize(market.min_base_amount ?? 0, market.min_quote_amount ?? 0, limitPx);
  const parsedClip = parseDecimal(displayQty);
  const clipNum = parsedClip != null && parsedClip > 0 ? parsedClip : 0;
  const sizeMin = minSizeHint(minSz, decimals, sizeNum);
  const offsetNum = parseDecimal(offsetBps) ?? 0;
  const floorNum = parseDecimal(chaseFloor) ?? NaN;
  const ceilNum = parseDecimal(chaseCeiling) ?? NaN;

  const setSizePct = (pct: number) => {
    if (maxSize <= 0) return;
    setSize(trimQty((maxSize * pct) / 100, decimals));
  };

  const onSlipChange = (raw: string) => {
    setSlippagePct(raw);
    persistSlipPct(raw);
  };

  const twapSlip =
    twapSlipFromMaxPrice(parseDecimal(twapMaxPrice) ?? 0, spot ?? 0) ??
    (parseFloat(slippagePct) || 0) / 100;
  const blockOpts = {
    tradingEnabled,
    feedReady: feed.ready,
    feedReason: feed.reason,
    sizeNum,
    symbol: market.symbol,
    decimals,
    kind,
    price,
    isMaker,
    minSz,
    algo,
    twapSec,
    twapSlip: parseDecimal(twapMaxPrice) != null ? twapSlip : null,
    twapAdvanced,
    twapFreqSec: twapAdvanced ? twapFreqSeconds(twapFreq) : null,
    floorNum,
    ceilNum,
    clipNum,
  };
  const sharedBlocked = ticketBlockReason(blockOpts);
  const buyBlocked = ticketBlockReason({ ...blockOpts, maxSize: maxBuy });
  const sellBlocked = ticketBlockReason({ ...blockOpts, maxSize: maxSell });

  const send = async (orderSide: "buy" | "sell") => {
    const blocked = orderSide === "buy" ? buyBlocked : sellBlocked;
    if (blocked || loading) return;
    const qSize = trimQty(sizeNum, decimals) || size;
    const qPrice = priceNum > 0 ? trimQty(priceNum, priceDecimals) || price : price;
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
    if (kind === "algo" && algo === "chase-iceberg") {
      const clip = trimQty(clipNum, decimals);
      if (!clip) return;
      const floor = canonicalDecimal(chaseFloor) ?? chaseFloor;
      const ceiling = canonicalDecimal(chaseCeiling) ?? chaseCeiling;
      setBusy(orderSide);
      try {
        const s = await api.chaseStart({
          market_index: market.market_index,
          side: orderSide,
          qty: canonicalDecimal(size) ?? qSize,
          display_qty: canonicalDecimal(displayQty) ?? clip,
          offset_bps:
            canonicalDecimal(offsetBps) ?? String(Number.isFinite(offsetNum) ? offsetNum : 4),
          price_floor: floor,
          price_ceiling: ceiling,
          reduce_only: reduceOnly,
        });
        setLiveAlgo(s);
        onOrderPlaced?.();
        const just = s.working?.[0];
        if (just?.status === "error") {
          notifyOrder({
            kind: "chase",
            status: "error",
            note: just.error || "Chase error",
            symbol: market.symbol,
          });
        } else if (just?.quote_action === "pause") {
          notifyOrder({
            kind: "chase",
            side: orderSide,
            size: just.rest_qty ?? clip,
            symbol: market.symbol,
            status: "paused",
            note: algoReasonLabel(just.reason) || "waiting",
          });
        } else {
          notifyOrder({
            kind: "chase",
            side: orderSide,
            size: just?.rest_qty ?? clip,
            symbol: market.symbol,
            price: just?.rest_price ?? undefined,
            status: "active",
          });
        }
      } catch (e) {
        notifyErr(e instanceof Error ? e.message : "Chase failed");
      } finally {
        setBusy(null);
      }
      return;
    }
    if (algo === "twap" && twapSec != null && twapAdvanced) {
      const freq = twapFreqSeconds(twapFreq);
      if (freq == null) return;
      setBusy(orderSide);
      try {
        const s = await api.twapStart({
          market_index: market.market_index,
          side: orderSide,
          qty: canonicalDecimal(size) ?? qSize,
          duration_seconds: twapSec,
          frequency_seconds: freq,
          style: twapStyle,
          randomize: twapRandomize,
          max_price: parseDecimal(twapMaxPrice) != null ? canonicalDecimal(twapMaxPrice) : null,
          max_index_pct: parseDecimal(twapIndexPct) != null ? canonicalDecimal(twapIndexPct) : null,
          reduce_only: reduceOnly,
        });
        setLiveAlgo(s);
        onOrderPlaced?.();
        notifyOrder({
          kind: "twap",
          status: "active",
          side: orderSide,
          size: qSize,
          symbol: market.symbol,
        });
      } catch (e) {
        notifyErr(e instanceof Error ? e.message : "Order failed");
      } finally {
        setBusy(null);
      }
      return;
    }
    if (algo === "twap" && twapSec != null) {
      await submit(
        () =>
          api.placeTwapOrder({
            market_index: market.market_index,
            side: orderSide,
            size: qSize,
            duration_seconds: twapSec,
            max_slippage:
              twapSlipFromMaxPrice(parseDecimal(twapMaxPrice) ?? 0, spot ?? 0) ??
              (slipFrac || 0.01),
            reduce_only: reduceOnly,
          }),
        { kind: "twap", size: qSize, symbol: market.symbol },
        orderSide
      );
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
          <div className="flex h-7 shrink-0 items-center border-b border-rule pr-1">
            <TabsList className="h-7 min-w-0 flex-1 justify-start gap-0 border-b-0 px-1.5">
              {ORDER_KINDS.filter((k) => k.id !== "algo").map((k) => (
                <TabsTrigger key={k.id} value={k.id} className="h-7 flex-1 px-1 text-xs">
                  {k.label}
                </TabsTrigger>
              ))}
              <Select
                value={algo}
                onOpenChange={(open) => {
                  if (open) setKind("algo");
                }}
                onValueChange={(v) => {
                  if (v === "chase-iceberg" || v === "twap") {
                    setAlgo(v);
                    setKind("algo");
                  }
                }}
              >
                <SelectTrigger
                  size="sm"
                  aria-label="Algo"
                  className={cn(
                    "h-7 min-w-0 flex-1 justify-center rounded-none border-0 border-b bg-transparent px-1 text-xs shadow-none dark:bg-transparent dark:hover:bg-transparent",
                    kind === "algo"
                      ? "border-text font-medium text-text"
                      : "border-transparent text-muted"
                  )}
                >
                  {kind === "algo" ? algoById(algo).label : "Algo"}
                </SelectTrigger>
                <SelectContent position="popper" align="center">
                  <SelectGroup>
                    {ALGOS.map((a) => (
                      <SelectItem key={a.id} value={a.id}>
                        {a.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </TabsList>
            {onClose ? <PanelCloseButton onClose={onClose} /> : null}
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <FieldGroup className="gap-3 px-2.5 py-2">
              <SizeField
                symbol={market.symbol}
                size={size}
                sizeNum={sizeNum}
                maxSize={maxSize}
                maxTitle={
                  reduceOnly
                    ? "Position size"
                    : "Available at this leverage. Opposite side includes close + flip."
                }
                decimals={decimals}
                minHint={sizeMin?.text}
                minHintWarn={sizeMin?.warn}
                onSizeChange={setSize}
                onSizePct={setSizePct}
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
                  onPriceChange={setPrice}
                  onTifChange={setTif}
                />
              </TabsContent>

              <TabsContent value="algo" className="mt-0">
                <AlgoParams
                  algo={algo}
                  market={market}
                  bookMid={mid}
                  displayQty={displayQty}
                  offsetBps={offsetBps}
                  chaseFloor={chaseFloor}
                  chaseCeiling={chaseCeiling}
                  twapHours={twapHours}
                  twapMinutes={twapMinutes}
                  twapMaxPrice={twapMaxPrice}
                  twapAdvanced={twapAdvanced}
                  twapRandomize={twapRandomize}
                  twapStyle={twapStyle}
                  twapFreq={twapFreq}
                  twapIndexPct={twapIndexPct}
                  sizeNum={sizeNum}
                  onDisplayQtyChange={setDisplayQty}
                  onOffsetBpsChange={setOffsetBps}
                  onChaseFloorChange={setChaseFloor}
                  onChaseCeilingChange={setChaseCeiling}
                  onTwapHoursChange={setTwapHours}
                  onTwapMinutesChange={setTwapMinutes}
                  onTwapMaxPriceChange={setTwapMaxPrice}
                  onTwapAdvancedChange={setTwapAdvanced}
                  onTwapRandomizeChange={setTwapRandomize}
                  onTwapStyleChange={setTwapStyle}
                  onTwapFreqChange={setTwapFreq}
                  onTwapIndexPctChange={setTwapIndexPct}
                />
              </TabsContent>
            </FieldGroup>
          </ScrollArea>

          <div className="flex shrink-0 items-center justify-between gap-2 px-2.5 py-2">
              <Field orientation="horizontal" className="w-auto items-center gap-1.5">
                <Switch
                  id="close-only"
                  checked={reduceOnly}
                  onCheckedChange={setReduceOnly}
                  aria-label="Close"
                />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <FieldLabel
                      htmlFor="close-only"
                      className="text-xs font-normal text-muted peer-data-[state=checked]:text-text"
                    >
                      Close
                    </FieldLabel>
                  </TooltipTrigger>
                  <TooltipContent>Reduces position only — will not open or flip</TooltipContent>
                </Tooltip>
              </Field>

              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setLevDraft(String(lev));
                  setLevOpen(true);
                }}
                className="shrink-0"
              >
                <span className="font-mono tabular-nums">{lev}x</span>
                <ChevronDown data-icon="inline-end" />
              </Button>
          </div>
        </Tabs>

        <Separator />
        <div className="shrink-0 px-2.5 py-2">
          {sharedBlocked ? (
            <p className="mb-1 text-center text-xs text-muted">{sharedBlocked}</p>
          ) : null}
          <div className="grid grid-cols-2 gap-1">
            <Button
              type="button"
              variant="buy"
              className="h-9 truncate px-1.5 text-sm font-semibold"
              disabled={loading || !!buyBlocked}
              title={buyBlocked ?? undefined}
              onClick={() => void send("buy")}
            >
              {busy === "buy"
                ? "Sending…"
                : !sharedBlocked && buyBlocked
                  ? buyBlocked
                  : orderCta({ kind, algo, side: "buy", base: market.symbol })}
            </Button>
            <Button
              type="button"
              variant="sell"
              className="h-9 truncate px-1.5 text-sm font-semibold"
              disabled={loading || !!sellBlocked}
              title={sellBlocked ?? undefined}
              onClick={() => void send("sell")}
            >
              {busy === "sell"
                ? "Sending…"
                : !sharedBlocked && sellBlocked
                  ? sellBlocked
                  : orderCta({ kind, algo, side: "sell", base: market.symbol })}
            </Button>
          </div>
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
    </div>
  );
}
