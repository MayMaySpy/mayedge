import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { algoReasonLabel, minutesToTwapSeconds, type AlgoId } from "@/lib/algos";
import { useTradingReady } from "@/hooks/useTradingReady";
import { api, type Market } from "@/lib/api";
import { setAlgo as setLiveAlgo, useLiveAccount, useLiveBbo } from "@/lib/liveData";
import { canonicalDecimal, parseDecimal } from "@/lib/numbers";
import { cn } from "@/lib/utils";
import { AlgoParams } from "./kinds/AlgoParams";
import { LimitParams } from "./kinds/LimitParams";
import { MarketParams } from "./kinds/MarketParams";
import { LeverageModal } from "./LeverageModal";
import {
  leveragePresets,
  loadSlipPct,
  makerMinSize,
  maxOrderSize,
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
  const [kind, setKind] = useState<OrderKind>("market");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [size, setSize] = useState("");
  const [price, setPrice] = useState("");
  const [slippagePct, setSlippagePct] = useState(loadSlipPct);
  const [reduceOnly, setReduceOnly] = useState(false);
  const [tif, setTif] = useState("gtt");
  const [algo, setAlgo] = useState<AlgoId>("twap");
  const [twapMinutes, setTwapMinutes] = useState("15");
  const [displayQty, setDisplayQty] = useState("");
  const [offsetBps, setOffsetBps] = useState("4");
  const [chaseFloor, setChaseFloor] = useState("");
  const [chaseCeiling, setChaseCeiling] = useState("");
  const [leverage, setLeverage] = useState("5");
  const [levOpen, setLevOpen] = useState(false);
  const [levDraft, setLevDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncedSymbol, setSyncedSymbol] = useState<string | null>(null);
  const bbo = useLiveBbo();
  const account = useLiveAccount();
  const tradeAvailable =
    parseFloat(account?.trade_available ?? account?.available ?? "0") || 0;
  const signedPos =
    parseFloat(
      account?.positions.find((p) => p.market_index === market?.market_index)?.size ?? "0"
    ) || 0;

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

  const submit = async (fn: () => Promise<unknown>, label: string) => {
    if (!tradingEnabled) {
      toast.error("Trading not configured. Add API credentials to backend .env");
      return;
    }
    setLoading(true);
    try {
      await fn();
      toast.success(label);
      onOrderPlaced?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Order failed");
    } finally {
      setLoading(false);
    }
  };

  const presets = leveragePresets(market);
  const maxLev = presets[presets.length - 1] ?? market.max_leverage ?? 20;
  const lev = presets.includes(parseInt(leverage, 10)) ? parseInt(leverage, 10) : maxLev;

  const applyLeverage = (value: string) => {
    const x = snapLeverage(presets, value);
    if (x == null) {
      toast.error("Enter a leverage");
      return;
    }
    setLeverage(String(x));
    setLevDraft(String(x));
    setLevOpen(false);
    if (!tradingEnabled) return;
    if (x !== lev) {
      submit(() => api.updateLeverage(market.market_index, x, true), `${x}x`);
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
  const worst =
    spot != null && slipFrac >= 0
      ? side === "buy"
        ? spot * (1 + slipFrac)
        : spot * (1 - slipFrac)
      : null;
  const sizeNum = parseDecimal(size) ?? 0;
  const decimals = market.size_decimals ?? 4;
  const priceDecimals = market.price_decimals ?? 4;
  const twapSec = minutesToTwapSeconds(twapMinutes);
  const priceNum = parseDecimal(price) ?? 0;
  const limitPx = kind === "limit" && priceNum > 0 ? priceNum : spot;
  const pxForMax =
    kind === "limit" && priceNum > 0
      ? priceNum
      : kind === "market" && worst != null && worst > 0
        ? worst
        : side === "buy"
          ? ask > 0
            ? ask
            : spot
          : bid > 0
            ? bid
            : spot;
  const maxSize = maxOrderSize({
    available: tradeAvailable,
    leverage: lev,
    price: pxForMax,
    signedPos,
    side,
    reduceOnly,
  });
  const isMaker = kind === "limit" && tif !== "ioc";
  const minSz = makerMinSize(market.min_base_amount ?? 0, market.min_quote_amount ?? 0, limitPx);
  const parsedClip = parseDecimal(displayQty);
  const clipNum = parsedClip != null && parsedClip > 0 ? parsedClip : 0;
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

  const blocked = ticketBlockReason({
    tradingEnabled,
    feedReady: feed.ready,
    feedReason: feed.reason,
    sizeNum,
    maxSize,
    symbol: market.symbol,
    decimals,
    kind,
    price,
    isMaker,
    minSz,
    algo,
    twapSec,
    floorNum,
    ceilNum,
    clipNum,
  });

  const cta = orderCta({
    kind,
    algo,
    side,
    base: market.symbol,
  });

  const send = async () => {
    if (blocked || loading) return;
    const qSize = trimQty(sizeNum, decimals) || size;
    const qPrice = priceNum > 0 ? trimQty(priceNum, priceDecimals) || price : price;
    if (kind === "market") {
      await submit(
        () =>
          api.placeMarketOrder({
            market_index: market.market_index,
            side,
            size: qSize,
            slippage: slipFrac || 0.01,
            reduce_only: reduceOnly,
          }),
        "Market order sent"
      );
      return;
    }
    if (kind === "limit") {
      await submit(
        () =>
          api.placeLimitOrder({
            market_index: market.market_index,
            side,
            size: qSize,
            price: qPrice,
            time_in_force: tif,
            reduce_only: reduceOnly,
          }),
        "Limit order sent"
      );
      return;
    }
    if (kind === "algo" && algo === "chase-iceberg") {
      const clip = trimQty(clipNum, decimals);
      if (!clip) return;
      const floor = canonicalDecimal(chaseFloor) ?? chaseFloor;
      const ceiling = canonicalDecimal(chaseCeiling) ?? chaseCeiling;
      setLoading(true);
      try {
        const s = await api.chaseStart({
          market_index: market.market_index,
          side,
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
          toast.error(just.error || "Chase error");
        } else if (just?.quote_action === "pause") {
          toast.message(
            `${just.algo_id ?? "Chase"} paused · ${algoReasonLabel(just.reason) || "waiting"}`
          );
        } else if (just?.rest_price) {
          toast.success(
            `${just.algo_id ?? "Chase"} active ${just.rest_qty ?? clip} @ ${just.rest_price}`
          );
        } else {
          toast.success(`${just?.algo_id ?? "Chase"} started`);
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Chase failed");
      } finally {
        setLoading(false);
      }
      return;
    }
    if (algo === "twap" && twapSec != null) {
      await submit(
        () =>
          api.placeTwapOrder({
            market_index: market.market_index,
            side,
            size: qSize,
            duration_seconds: twapSec,
            max_slippage: slipFrac || 0.01,
            reduce_only: reduceOnly,
          }),
        "TWAP order sent"
      );
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PanelHeader
        title={
          <span className="min-w-0 truncate font-mono text-[12px] font-medium text-text">
            {market.symbol}
          </span>
        }
        onClose={onClose}
      />

      <form
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <ToggleGroup
          type="single"
          value={side}
          onValueChange={(v) => {
            if (v === "buy" || v === "sell") setSide(v);
          }}
          className={cn(
            "grid w-full shrink-0 grid-cols-2 gap-0 rounded-none",
            side === "buy"
              ? "shadow-[inset_0_2px_0_0_var(--color-bid)]"
              : "shadow-[inset_0_2px_0_0_var(--color-ask)]"
          )}
        >
          <ToggleGroupItem
            value="buy"
            className={cn(
              "h-8 rounded-none text-xs font-semibold tracking-wide data-[state=on]:bg-bid/15 data-[state=on]:text-bid",
              side !== "buy" && "text-muted"
            )}
          >
            Buy
          </ToggleGroupItem>
          <ToggleGroupItem
            value="sell"
            className={cn(
              "h-8 rounded-none text-xs font-semibold tracking-wide data-[state=on]:bg-ask/15 data-[state=on]:text-ask",
              side !== "sell" && "text-muted"
            )}
          >
            Sell
          </ToggleGroupItem>
        </ToggleGroup>

        <Tabs
          value={kind}
          onValueChange={(v) => setKind(v as OrderKind)}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <TabsList className="h-7 w-full shrink-0 justify-start gap-0 px-1.5">
            {ORDER_KINDS.map((k) => (
              <TabsTrigger key={k.id} value={k.id} className="h-7 flex-1 px-1 text-[11px]">
                {k.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-hidden px-2 pt-1.5 pb-1.5">
            <SizeField
              symbol={market.symbol}
              size={size}
              sizeNum={sizeNum}
              maxSize={maxSize}
              maxTitle={
                reduceOnly
                  ? "Position size"
                  : (side === "buy" && signedPos < 0) || (side === "sell" && signedPos > 0)
                    ? "Close + flip: 2× position + free margin at leverage"
                    : "Trade margin × leverage / price (includes multi-asset haircut)"
              }
              decimals={decimals}
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
                twapMinutes={twapMinutes}
                slippagePct={slippagePct}
                worst={worst}
                onAlgoChange={setAlgo}
                onDisplayQtyChange={setDisplayQty}
                onOffsetBpsChange={setOffsetBps}
                onChaseFloorChange={setChaseFloor}
                onChaseCeilingChange={setChaseCeiling}
                onTwapMinutesChange={setTwapMinutes}
                onSlipChange={onSlipChange}
              />
            </TabsContent>

            <div className="mt-auto flex items-center justify-between gap-2">
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
                      className="text-[11px] font-normal text-muted peer-data-[state=checked]:text-text"
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
                className="h-auto shrink-0 gap-0.5 px-1"
              >
                <span className="font-mono text-sm tabular-nums text-text">{lev}x</span>
                <ChevronDown className="size-3 text-muted" />
              </Button>
            </div>
          </div>
        </Tabs>

        <div className="shrink-0 border-t border-rule px-2 py-1.5">
          <Button
            type="submit"
            variant={side === "buy" ? "buy" : "sell"}
            className="h-9 w-full text-[13px] transition-[filter,transform] duration-150 active:scale-[0.99]"
            disabled={loading || !!blocked}
          >
            {loading ? "Sending…" : blocked ?? cta}
          </Button>
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
