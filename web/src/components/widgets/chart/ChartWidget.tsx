import { type IChartApi, type ISeriesApi, type CandlestickData } from "lightweight-charts";
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { ScanTab } from "@/components/widgets/ScanBoard";
import {
  api,
  type AccountTrade,
  type Candle,
  type LiquidationSummaryHours,
  type Market,
  type OpenInterestSample,
} from "@/lib/api";
import { useAxisTicket } from "@/lib/axisTicket";
import { chartDraftFor, clearChartDraft, draftReady, requestChartDraftOpen, useChartPlan } from "@/lib/chartDraft";
import { aggregateCandles, candleTime, foldMinutes, mergeCandles } from "@/lib/chartCandles";
import { TopOfBookPrimitive } from "@/lib/chartTopOfBook";
import { TradingLinesPrimitive, type ChartOverlay, type OverlayAction } from "@/lib/chartTradingLines";
import { useWatchPopped } from "@/lib/deskBridge";
import { fillMarks, type FillMark } from "@/lib/fillMarks";
import { FillMarksPrimitive, type FillSpot } from "@/lib/fillMarkPrimitive";
import { buildFundingBars, isSettled, type FundingBar, type FundingSample } from "@/lib/funding";
import { loadLiqHours } from "@/lib/liqHours";
import {
  useLiveAccountTrades,
  useLiveCandles1s,
  useLiveFundingRate,
  useLiveMinuteCandles,
  useLiveOpenInterest,
  useLiveTopOfBook,
} from "@/lib/liveData";
import { bucketOpen, buildOiLine, type OiLinePoint } from "@/lib/openInterest";
import { useQuickPanel } from "@/lib/quickPanel";
import { createTicketAmend, type DraftMove, type TicketAmend } from "@/lib/ticketAmend";
import { createTicketPlace, type TicketPlace } from "@/lib/ticketPlace";
import { candleSource, loadPins, loadTimeframe, parseTimeframe, supportsOpenInterest } from "@/lib/timeframe";
import { loadWatchWindow, type WatchWindow } from "@/lib/watchWindow";

import type { Ohlc } from "./chartFormat";
import { loadBbo, loadFills, loadFund, loadMayRekt, loadMode, loadOi, loadScanTab, loadVol, type ChartMode } from "./chartPrefs";
import { ChartFrame } from "./ChartFrame";
import { useChartFeed } from "./useChartFeed";
import { useChartSeries } from "./useChartSeries";
import { useChartTicketInteraction, type QtyEditState } from "./useChartTicketInteraction";


export type { ChartOverlay, OverlayAction, TicketAmend, TicketPlace };



interface ChartWidgetProps {
  symbol: string;
  priceDecimals?: number;
  overlays?: ChartOverlay[];
  livePrice?: number | null;
  onOverlayAction?: (action: OverlayAction, overlay: ChartOverlay) => void;
  onTicketAmend?: (amend: TicketAmend) => void;
  onTicketPlace?: (place: TicketPlace) => void;
  onPlanClick?: (price: number) => void;
  onDraftMove?: (move: DraftMove) => void;
  onClose?: () => void;
  children?: ReactNode;
  markets?: readonly Market[];
  onSymbolChange?: (symbol: string) => void;
}



const EMPTY_CANDLES: Candle[] = [];
const EMPTY_FILLS: FillMark[] = [];
const EMPTY_SPOTS: FillSpot[] = [];
const EMPTY_OI: OpenInterestSample[] = [];
const EMPTY_OI_LINE: OiLinePoint[] = [];
const EMPTY_FUNDING: FundingSample[] = [];
const EMPTY_FUND_BARS: FundingBar[] = [];


export const ChartWidget = memo(function ChartWidget({
  symbol,
  priceDecimals = 2,
  overlays = [],
  livePrice = null,
  onOverlayAction,
  onTicketAmend,
  onTicketPlace,
  onPlanClick,
  onDraftMove,
  onClose,
  children,
  markets = [],
  onSymbolChange,
}: ChartWidgetProps) {
  const [tf, setTf] = useState(loadTimeframe);
  const [pins, setPins] = useState(loadPins);
  const bar = useMemo(
    () => parseTimeframe(tf) ?? parseTimeframe("1m")!,
    [tf]
  );
  const [volOn, setVolOn] = useState(loadVol);
  const [oiOn, setOiOn] = useState(loadOi);
  const [fundOn, setFundOn] = useState(loadFund);
  const [bboOn, setBboOn] = useState(loadBbo);
  const [mayRektOn, setMayRektOn] = useState(loadMayRekt);
  const [fillsOn, setFillsOn] = useState(loadFills);
  const [mode, setMode] = useState<ChartMode>(loadMode);
  const [scanTab, setScanTab] = useState<ScanTab>(loadScanTab);
  const [watchWindow, setWatchWindow] = useState<WatchWindow>(loadWatchWindow);
  const [liqHours, setLiqHours] = useState<LiquidationSummaryHours>(() => loadLiqHours(24));
  const popped = useWatchPopped();
  const isWatch = mode === "watch" && !popped;
  const isScan = mode === "scan";
  const isPrice = !isWatch && !isScan;
  const [hist, setHist] = useState<{ key: string; candles: Candle[] }>({
    key: "",
    candles: [],
  });
  const [hover, setHover] = useState<{
    key: string;
    bar: Ohlc;
    oi: number | null;
    fund: { apr: number; settled: boolean } | null;
    time: number | null;
  } | null>(null);
  const [qtyEdit, setQtyEdit] = useState<QtyEditState | null>(null);
  const [oiHist, setOiHist] = useState<{ key: string; points: OpenInterestSample[] }>({
    key: "",
    points: [],
  });
  const [fundHist, setFundHist] = useState<{ key: string; points: FundingSample[] }>({
    key: "",
    points: [],
  });
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000));
  const fromSeconds = candleSource(bar) === "1s";
  const candles1s = useLiveCandles1s(isPrice && fromSeconds);
  const minuteCandles = useLiveMinuteCandles();
  const top = useLiveTopOfBook();
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const fillMarksRef = useRef<FillMarksPrimitive | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const oiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const fundSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const tradingLinesRef = useRef<TradingLinesPrimitive | null>(null);
  const topOfBookRef = useRef<TopOfBookPrimitive | null>(null);
  const overlaysRef = useRef(overlays);
  const topRef = useRef(top);
  const bboOnRef = useRef(bboOn);
  const onActionRef = useRef(onOverlayAction);
  const onAmendRef = useRef(onTicketAmend);
  const onPlaceRef = useRef(onTicketPlace);
  const livePriceRef = useRef(livePrice);
  const priceDecimalsRef = useRef(priceDecimals);
  const amendRef = useRef<ReturnType<typeof createTicketAmend> | null>(null);
  const placeRef = useRef<ReturnType<typeof createTicketPlace> | null>(null);
  const ghostRef = useRef<ChartOverlay | null>(null);
  const suppressClickRef = useRef(false);
  const sizeClickRef = useRef<ChartOverlay | null>(null);
  const paintLinesRef = useRef<() => void>(() => {});
  const { armed: axisArmed, setArmed: setAxisArmed } = useAxisTicket();
  const { armed: planArmed } = useChartPlan();
  const planArmedRef = useRef(planArmed);
  const onPlanClickRef = useRef(onPlanClick);
  const onDraftMoveRef = useRef(onDraftMove);
  const onDraftClearRef = useRef<() => void>(() => {});
  const onDraftEnterRef = useRef<() => boolean>(() => false);
  useEffect(() => {
    planArmedRef.current = planArmed;
    onPlanClickRef.current = onPlanClick;
    onDraftMoveRef.current = onDraftMove;
  }, [planArmed, onPlanClick, onDraftMove]);
  useEffect(() => {
    onDraftClearRef.current = () => clearChartDraft(symbol);
    onDraftEnterRef.current = () => {
      if (!draftReady(chartDraftFor(symbol))) return false;
      requestChartDraftOpen();
      return true;
    };
  }, [symbol]);
  const { open: quickOn, setOpen: setQuickOn } = useQuickPanel();
  const axisArmedRef = useRef(axisArmed);
  const volOnRef = useRef(volOn);
  const primedRef = useRef(false);
  const toneBarsRef = useRef<CandlestickData[] | null>(null);
  const toneStampAt = useRef(0);
  const lastMetaRef = useRef<{ first: number; time: number; len: number } | null>(null);
  const [paintGen, setPaintGen] = useState(0);
  const seriesKey = `${symbol}:${tf}`;
  const seriesKeyRef = useRef(seriesKey);
  const histBars = hist.key === seriesKey ? hist.candles : EMPTY_CANDLES;
  const hoverBar = hover?.key === seriesKey ? hover.bar : null;
  const showOi = isPrice && oiOn && supportsOpenInterest(bar);
  const oiSamples = oiHist.key === seriesKey ? oiHist.points : EMPTY_OI;
  const showFund = isPrice && fundOn && supportsOpenInterest(bar);
  const fundSamples = fundHist.key === seriesKey ? fundHist.points : EMPTY_FUNDING;
  const liveFills = useLiveAccountTrades();
  const [fillPage, setFillPage] = useState<{ key: number; rows: AccountTrade[] } | null>(null);
  const chartMarket = useMemo(() => {
    const key = symbol.toUpperCase();
    return (
      markets.find((m) => m.symbol.toUpperCase() === key && m.is_perp !== false) ??
      markets.find((m) => m.symbol.toUpperCase() === key) ??
      null
    );
  }, [markets, symbol]);
  const quotedOi = useLiveOpenInterest(chartMarket?.market_index);
  const liveOi = useMemo(() => {
    const oi = quotedOi ?? chartMarket?.open_interest ?? null;
    return oi != null && Number.isFinite(oi) && oi > 0 ? oi : null;
  }, [chartMarket, quotedOi]);
  const quotedFunding = useLiveFundingRate(chartMarket?.market_index);
  const liveFunding = useMemo(() => {
    const rate = quotedFunding ?? chartMarket?.funding_rate ?? null;
    return rate != null && Number.isFinite(rate) ? rate : null;
  }, [chartMarket, quotedFunding]);
  const fillMarkList = useMemo(() => {
    if (!isPrice || !chartMarket || !fillsOn) return EMPTY_FILLS;
    const rest = fillPage?.key === chartMarket.market_index ? fillPage.rows : [];
    return fillMarks([...rest, ...liveFills], chartMarket.market_index, bar.seconds);
  }, [isPrice, chartMarket, fillsOn, fillPage, liveFills, bar.seconds]);
  const hoverFills =
    hover?.key === seriesKey && hover.time != null
      ? fillMarkList.filter((mark) => mark.time === hover.time)
      : EMPTY_FILLS;

  useEffect(() => {
    const index = chartMarket?.market_index;
    if (!isPrice || index == null) return;
    let cancelled = false;
    void api
      .accountTrades({ market_index: index, limit: 100 })
      .then((page) => {
        if (!cancelled) setFillPage({ key: index, rows: page.trades });
      })
      .catch(() => {
        if (!cancelled) setFillPage({ key: index, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [isPrice, chartMarket?.market_index]);

  const oiLine = useMemo(() => {
    if (!supportsOpenInterest(bar) || !oiOn || !isPrice) return EMPTY_OI_LINE;
    const step = bar.seconds;
    const live = liveOi != null ? { time: bucketOpen(nowSec, step), value: liveOi } : null;
    return buildOiLine(oiSamples, step, live);
  }, [isPrice, oiOn, bar, oiSamples, liveOi, nowSec]);
  const oiLineRef = useRef(oiLine);
  const oiShape = oiLine.map((point) => point.time).join(",");

  const fundBars = useMemo(() => {
    if (!showFund) return EMPTY_FUND_BARS;
    const step = bar.seconds;
    const live =
      liveFunding != null ? { time: bucketOpen(nowSec, step), rate: liveFunding } : null;
    return buildFundingBars(fundSamples, step, live);
  }, [showFund, bar, fundSamples, liveFunding, nowSec]);
  const fundBarsRef = useRef(fundBars);
  const fundShape = fundBars
    .map((point) => `${point.time}${isSettled(point) ? "s" : ""}`)
    .join(",");

  const marketByIndex = useMemo(
    () => new Map(markets.map((m) => [m.market_index, m])),
    [markets]
  );
  const shownQtyEdit =
    qtyEdit && overlays.some((o) => o.id === qtyEdit.overlayId && o.qtyEditable)
      ? qtyEdit
      : null;

  useChartFeed({
    shownQtyEdit,
    setQtyEdit,
    tradingLinesRef,
    oiLine,
    fundBars,
    oiLineRef,
    fundBarsRef,
    seriesKey,
    seriesKeyRef,
    overlays,
    overlaysRef,
    amendRef,
    placeRef,
    ghostRef,
    onOverlayAction,
    onTicketAmend,
    onTicketPlace,
    onActionRef,
    onAmendRef,
    onPlaceRef,
    livePrice,
    livePriceRef,
    priceDecimals,
    priceDecimalsRef,
    axisArmed,
    axisArmedRef,
    volOn,
    volOnRef,
    top,
    topRef,
    bboOn,
    bboOnRef,
    isPrice,
    fromSeconds,
    symbol,
    bar,
    tf,
    showOi,
    showFund,
    setHist,
    setOiHist,
    setFundHist,
    setNowSec,
  });


  const display = useMemo(() => {
    if (fromSeconds) {
      return bar.seconds === 1 ? candles1s : aggregateCandles(candles1s, bar.seconds);
    }
    // 1m: never drop REST history when a short live stream arrives.
    if (bar.seconds === 60) return mergeCandles(histBars, minuteCandles);
    return foldMinutes(histBars, minuteCandles, bar.seconds);
  }, [fromSeconds, bar, candles1s, minuteCandles, histBars]);

  const fillSpots = useMemo(() => {
    if (!fillMarkList.length || !display.length) return EMPTY_SPOTS;
    const bars = new Map<number, { high: number; low: number }>();
    for (const candle of display) {
      const t = candleTime(candle.time) as number;
      bars.set(t, { high: candle.high, low: candle.low });
    }
    const spots: FillSpot[] = [];
    for (const mark of fillMarkList) {
      const bar = bars.get(mark.time);
      if (!bar) continue;
      spots.push({ time: mark.time, side: mark.side, high: bar.high, low: bar.low });
    }
    return spots;
  }, [fillMarkList, display]);
  const fillSpotRef = useRef<FillSpot[]>(EMPTY_SPOTS);

  useEffect(() => {
    fillSpotRef.current = fillSpots;
    fillMarksRef.current?.setMarks(fillSpots);
  }, [fillSpots]);

  useChartTicketInteraction({
    isPrice,
    priceDecimals,
    setHover,
    setQtyEdit,
    containerRef,
    wrapRef,
    chartRef,
    seriesRef,
    fillMarksRef,
    volSeriesRef,
    oiSeriesRef,
    fundSeriesRef,
    tradingLinesRef,
    topOfBookRef,
    overlaysRef,
    topRef,
    bboOnRef,
    onActionRef,
    onAmendRef,
    onPlaceRef,
    livePriceRef,
    priceDecimalsRef,
    amendRef,
    placeRef,
    ghostRef,
    suppressClickRef,
    sizeClickRef,
    paintLinesRef,
    axisArmedRef,
    planArmedRef,
    onPlanClickRef,
    onDraftMoveRef,
    onDraftClearRef,
    onDraftEnterRef,
    volOnRef,
    primedRef,
    lastMetaRef,
    seriesKeyRef,
    fillSpotRef,
  });


  useChartSeries({
    showOi,
    showFund,
    oiShape,
    fundShape,
    liveOi,
    nowSec,
    liveFunding,
    priceDecimals,
    symbol,
    tf,
    bar,
    display,
    volOn,
    mayRektOn,
    paintGen,
    setPaintGen,
    overlays,
    axisArmed,
    top,
    bboOn,
    chartRef,
    oiSeriesRef,
    fundSeriesRef,
    seriesRef,
    volSeriesRef,
    oiLineRef,
    fundBarsRef,
    toneBarsRef,
    toneStampAt,
    primedRef,
    lastMetaRef,
    fillMarksRef,
    fillSpotRef,
    paintLinesRef,
    topOfBookRef,
  });


  return (
    <ChartFrame
      symbol={symbol}
      markets={markets}
      onSymbolChange={onSymbolChange}
      onClose={onClose}
      priceDecimals={priceDecimals}
      tf={tf}
      setTf={setTf}
      pins={pins}
      setPins={setPins}
      mode={mode}
      setMode={setMode}
      scanTab={scanTab}
      setScanTab={setScanTab}
      watchWindow={watchWindow}
      setWatchWindow={setWatchWindow}
      volOn={volOn}
      setVolOn={setVolOn}
      oiOn={oiOn}
      setOiOn={setOiOn}
      fundOn={fundOn}
      setFundOn={setFundOn}
      bboOn={bboOn}
      setBboOn={setBboOn}
      mayRektOn={mayRektOn}
      setMayRektOn={setMayRektOn}
      fillsOn={fillsOn}
      setFillsOn={setFillsOn}
      axisArmed={axisArmed}
      setAxisArmed={setAxisArmed}
      quickOn={quickOn}
      setQuickOn={setQuickOn}
      liqHours={liqHours}
      setLiqHours={setLiqHours}
      isPrice={isPrice}
      isScan={isScan}
      isWatch={isWatch}
      popped={popped}
      showOi={showOi}
      showFund={showFund}
      bar={bar}
      wrapRef={wrapRef}
      containerRef={containerRef}
      shownQtyEdit={shownQtyEdit}
      setQtyEdit={setQtyEdit}
      marketByIndex={marketByIndex}
      amendRef={amendRef}
      onAmendRef={onAmendRef}
      display={display}
      hover={hover}
      hoverBar={hoverBar}
      seriesKey={seriesKey}
      liveOi={liveOi}
      fundBars={fundBars}
      hoverFills={hoverFills}
    >
      {children}
    </ChartFrame>
  );
});
