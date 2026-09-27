import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type MouseEventParams,
} from "lightweight-charts";
import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { PanelCloseButton } from "@/components/desk/PanelHeader";
import { loadLiqHours } from "@/components/widgets/LiquidationHeatTable";
import { ScanBoard, type ScanTab } from "@/components/widgets/ScanBoard";
import { TimeframePins } from "@/components/widgets/TimeframePins";
import { WatchBoard } from "@/components/widgets/WatchBoard";
import {
  api,
  type Candle,
  type LiquidationSummaryHours,
  type Market,
  type OpenInterestSample,
} from "@/lib/api";
import { openWatchWindow, useWatchPopped } from "@/lib/deskBridge";
import { rankRelativeStrength } from "@/lib/relativeStrength";
import {
  aggregateCandles,
  foldMinutes,
  formatBarVolume,
  mergeCandles,
  candleTime,
  shouldReplaceChartData,
  toSeriesData,
} from "@/lib/chartCandles";
import {
  parseOverlayAction,
  TradingLinesPrimitive,
  type ChartOverlay,
  type OverlayAction,
} from "@/lib/chartTradingLines";
import { candleTones, tonePaint } from "@/lib/mayRekt";
import { TopOfBookPrimitive } from "@/lib/chartTopOfBook";
import { useAxisTicket } from "@/lib/axisTicket";
import { useQuickPanel } from "@/lib/quickPanel";
import { getQuickSize } from "@/lib/quickSizes";
import {
  createTicketAmend,
  type TicketAmend,
  type TicketAmendHost,
} from "@/lib/ticketAmend";
import { createTicketPlace, type TicketPlace } from "@/lib/ticketPlace";
import {
  rollLiveCandles,
  seedCandles1s,
  useLiveCandles1s,
  useLiveMinuteCandles,
  useLiveQuotes,
  useLiveTopOfBook,
} from "@/lib/liveData";
import { bucketOpen, buildOiLine, type OiLinePoint } from "@/lib/openInterest";
import { theme } from "@/lib/theme";
import {
  candleSource,
  loadPins,
  loadTimeframe,
  parseTimeframe,
  persistPins,
  persistTimeframe,
  showsSeconds,
  supportsOpenInterest,
} from "@/lib/timeframe";
import { cn, formatPct, formatPrice, formatSize, formatUsdCompact } from "@/lib/utils";
import {
  WATCH_WINDOWS,
  WATCH_WINDOW_SEC,
  loadWatchWindow,
  persistWatchWindow,
  type WatchWindow,
} from "@/lib/watchWindow";
import { SquareArrowOutUpRight } from "lucide-react";

export type { ChartOverlay, OverlayAction, TicketAmend, TicketPlace };

const VOL_KEY = "mayedge-chart-vol";
const OI_KEY = "mayedge-chart-oi";
const BBO_KEY = "mayedge-chart-bbo";
const MAYREKT_KEY = "mayedge-chart-mayrekt";
const MODE_KEY = "mayedge-chart-mode";
const SCAN_TAB_KEY = "mayedge-scan-tab";
const RIGHT_OFFSET = 8;

const CHART_MODES = ["price", "scan", "watch"] as const;
type ChartMode = (typeof CHART_MODES)[number];
const SCAN_TABS = ["rel", "liqs"] as const;

interface ChartWidgetProps {
  symbol: string;
  priceDecimals?: number;
  overlays?: ChartOverlay[];
  livePrice?: number | null;
  onOverlayAction?: (action: OverlayAction, overlay: ChartOverlay) => void;
  onTicketAmend?: (amend: TicketAmend) => void;
  onTicketPlace?: (place: TicketPlace) => void;
  onClose?: () => void;
  children?: ReactNode;
  markets?: readonly Market[];
  onSymbolChange?: (symbol: string) => void;
}

function chartPoint(el: HTMLElement, e: PointerEvent) {
  const r = el.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

function chartRegion(
  chart: IChartApi,
  pt: { x: number; y: number }
): "axis" | "pane" | "elsewhere" {
  let paneW = 0;
  let paneH = 0;
  try {
    const pane = chart.paneSize();
    paneW = pane?.width ?? 0;
    paneH = pane?.height ?? 0;
  } catch {
    return "elsewhere";
  }
  if (!(paneW > 0) || !(paneH > 0) || pt.x < 0 || pt.y < 0 || pt.y > paneH) return "elsewhere";
  if (pt.x >= paneW) return "axis";
  return "pane";
}

function axisGhost(price: number, side: "buy" | "sell"): ChartOverlay {
  const qty = getQuickSize();
  const n = parseFloat(qty);
  const size = Number.isFinite(n) && n > 0 ? formatSize(n) : "";
  return {
    id: "axis-ghost",
    kind: "order",
    price,
    color: side === "buy" ? theme.bid : theme.ask,
    label: size ? `${side === "buy" ? "BUY" : "SELL"} ${size}` : side === "buy" ? "BUY" : "SELL",
    side,
    interactive: false,
  };
}

function stampMayRekt(bars: CandlestickData[], source: Candle[]): CandlestickData[] {
  const tones = candleTones(source);
  const byTime = new Map<number, { color: string; borderColor: string; wickColor: string }>();
  source.forEach((bar, i) => {
    const tone = tones[i];
    if (!tone) return;
    byTime.set(candleTime(bar.time) as number, tonePaint(tone));
  });
  return bars.map((bar) => {
    const paint = byTime.get(bar.time as number);
    if (!paint) return bar;
    return { ...bar, color: paint.color, borderColor: paint.borderColor, wickColor: paint.wickColor };
  });
}

function priceFormat(decimals: number) {
  const d = Math.max(0, Math.min(8, Math.floor(decimals)));
  return {
    type: "price" as const,
    precision: d,
    minMove: d === 0 ? 1 : 10 ** -d,
  };
}

function loadVol(): boolean {
  try {
    return localStorage.getItem(VOL_KEY) === "1";
  } catch {
    return false;
  }
}

function loadOi(): boolean {
  try {
    return localStorage.getItem(OI_KEY) === "1";
  } catch {
    return false;
  }
}

function loadBbo(): boolean {
  try {
    return localStorage.getItem(BBO_KEY) === "1";
  } catch {
    return false;
  }
}

function loadMayRekt(): boolean {
  try {
    return localStorage.getItem(MAYREKT_KEY) === "1";
  } catch {
    return false;
  }
}

function loadMode(): ChartMode {
  try {
    const raw = localStorage.getItem(MODE_KEY);
    if (raw === "rs" || raw === "scan") {
      if (raw === "rs") {
        try {
          localStorage.setItem(MODE_KEY, "scan");
        } catch {
          /* ignore */
        }
      }
      return "scan";
    }
    if (raw === "price") return "price";
    if (raw === "watch") return "watch";
  } catch {
    /* ignore */
  }
  return "price";
}

function loadScanTab(): ScanTab {
  try {
    const raw = localStorage.getItem(SCAN_TAB_KEY);
    if (raw === "rel" || raw === "liqs") return raw;
  } catch {
    /* ignore */
  }
  return "rel";
}

const EMPTY_CANDLES: Candle[] = [];
const EMPTY_OI: OpenInterestSample[] = [];
const EMPTY_OI_LINE: OiLinePoint[] = [];

type Ohlc = { open: number; high: number; low: number; close: number; volume?: number };

function sameOhlc(a: Ohlc | null, b: Ohlc | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.open === b.open &&
    a.high === b.high &&
    a.low === b.low &&
    a.close === b.close &&
    a.volume === b.volume
  );
}

function ohlcOf(c: Candle | CandlestickData | Ohlc | null | undefined, volume?: number): Ohlc | null {
  if (!c) return null;
  if (!Number.isFinite(c.open) || !Number.isFinite(c.close)) return null;
  const vol = volume ?? ("volume" in c && Number.isFinite(c.volume) ? c.volume : undefined);
  return { open: c.open, high: c.high, low: c.low, close: c.close, volume: vol };
}

function applyVolumeLayout(series: ISeriesApi<"Candlestick">, on: boolean) {
  series.priceScale().applyOptions({
    scaleMargins: { top: 0.08, bottom: on ? 0.22 : 0.08 },
  });
}

function OhlcReadout({
  bar,
  decimals,
  showVolume,
  showOi,
  oi,
}: {
  bar: Ohlc | null;
  decimals: number;
  showVolume?: boolean;
  showOi?: boolean;
  oi?: number | null;
}) {
  if (!bar) {
    return <span className="font-mono text-sm text-muted-foreground">—</span>;
  }
  const up = bar.close >= bar.open;
  const tone = up ? "text-bid" : "text-ask";
  const chg = bar.open !== 0 ? ((bar.close - bar.open) / bar.open) * 100 : null;
  return (
    <span className="flex min-w-0 items-baseline gap-2 overflow-hidden font-mono text-sm tabular-nums">
      <OhlcField k="O" v={bar.open} decimals={decimals} className={tone} />
      <OhlcField k="H" v={bar.high} decimals={decimals} className={tone} />
      <OhlcField k="L" v={bar.low} decimals={decimals} className={tone} />
      <OhlcField k="C" v={bar.close} decimals={decimals} className={tone} />
      {chg != null && <span className={cn("shrink-0", tone)}>{formatPct(chg)}</span>}
      {showVolume ? (
        <span className="inline-flex shrink-0 items-baseline gap-1">
          <span className="text-muted-foreground">V</span>
          <span className="text-muted-foreground">{formatBarVolume(bar.volume ?? 0)}</span>
        </span>
      ) : null}
      {showOi ? (
        <span className="inline-flex shrink-0 items-baseline gap-1">
          <span className="text-muted-foreground">OI</span>
          <span className="text-muted-foreground">{formatUsdCompact(oi) || "—"}</span>
        </span>
      ) : null}
    </span>
  );
}

function OhlcField({
  k,
  v,
  decimals,
  className,
}: {
  k: string;
  v: number;
  decimals: number;
  className?: string;
}) {
  return (
    <span className="inline-flex shrink-0 items-baseline gap-1">
      <span className="text-muted-foreground">{k}</span>
      <span className={className}>{formatPrice(v, decimals)}</span>
    </span>
  );
}

function liqWindowLabel(hours: LiquidationSummaryHours): string {
  if (hours === 168) return "7d";
  if (hours === 720) return "30d";
  return `${hours}h`;
}

function LiqsReadout({ hours }: { hours: LiquidationSummaryHours }) {
  return (
    <span className="font-mono text-sm text-muted-foreground tabular-nums">
      {liqWindowLabel(hours)} liqs
    </span>
  );
}

function NumeraireReadout({ change }: { change: number | null }) {
  if (change == null) {
    return <span className="font-mono text-sm text-muted-foreground">BTC 24h —</span>;
  }
  const tone = change > 0 ? "text-bid" : change < 0 ? "text-ask" : "text-muted-foreground";
  return (
    <span className="flex min-w-0 items-baseline gap-2 overflow-hidden font-mono text-sm tabular-nums">
      <span className="text-muted-foreground">vs BTC</span>
      <span className={cn("shrink-0", tone)}>{formatPct(change)}</span>
    </span>
  );
}

export const ChartWidget = memo(function ChartWidget({
  symbol,
  priceDecimals = 2,
  overlays = [],
  livePrice = null,
  onOverlayAction,
  onTicketAmend,
  onTicketPlace,
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
  const [bboOn, setBboOn] = useState(loadBbo);
  const [mayRektOn, setMayRektOn] = useState(loadMayRekt);
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
  const [hover, setHover] = useState<{ key: string; bar: Ohlc; oi: number | null } | null>(null);
  const [oiHist, setOiHist] = useState<{ key: string; points: OpenInterestSample[] }>({
    key: "",
    points: [],
  });
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000));
  const fromSeconds = candleSource(bar) === "1s";
  const candles1s = useLiveCandles1s(isPrice && fromSeconds);
  const minuteCandles = useLiveMinuteCandles();
  const quotes = useLiveQuotes();
  const top = useLiveTopOfBook();
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const oiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
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
  const paintLinesRef = useRef<() => void>(() => {});
  const { armed: axisArmed, setArmed: setAxisArmed } = useAxisTicket();
  const { open: quickOn, setOpen: setQuickOn } = useQuickPanel();
  const axisArmedRef = useRef(axisArmed);
  const volOnRef = useRef(volOn);
  const primedRef = useRef(false);
  const lastMetaRef = useRef<{ first: number; time: number; len: number } | null>(null);
  const [paintGen, setPaintGen] = useState(0);
  const seriesKey = `${symbol}:${tf}`;
  const seriesKeyRef = useRef(seriesKey);
  const histBars = hist.key === seriesKey ? hist.candles : EMPTY_CANDLES;
  const hoverBar = hover?.key === seriesKey ? hover.bar : null;
  const showOi = isPrice && oiOn && supportsOpenInterest(bar);
  const oiSamples = oiHist.key === seriesKey ? oiHist.points : EMPTY_OI;
  const liveOi = useMemo(() => {
    const key = symbol.toUpperCase();
    const market =
      markets.find((m) => m.symbol.toUpperCase() === key && m.is_perp !== false) ??
      markets.find((m) => m.symbol.toUpperCase() === key);
    if (!market) return null;
    const oi = quotes[market.market_index]?.open_interest ?? market.open_interest;
    return oi != null && Number.isFinite(oi) && oi > 0 ? oi : null;
  }, [markets, quotes, symbol]);
  const oiLine = useMemo(() => {
    if (!supportsOpenInterest(bar) || !oiOn || !isPrice) return EMPTY_OI_LINE;
    const step = bar.seconds;
    const live = liveOi != null ? { time: bucketOpen(nowSec, step), value: liveOi } : null;
    return buildOiLine(oiSamples, step, live);
  }, [isPrice, oiOn, bar, oiSamples, liveOi, nowSec]);
  const oiLineRef = useRef(oiLine);
  const oiShape = oiLine.map((point) => point.time).join(",");

  useEffect(() => {
    oiLineRef.current = oiLine;
  }, [oiLine]);

  useEffect(() => {
    seriesKeyRef.current = seriesKey;
  }, [seriesKey]);

  useEffect(() => {
    overlaysRef.current = overlays;
    amendRef.current?.setOverlays(overlays);
  }, [overlays]);

  useEffect(() => {
    onActionRef.current = onOverlayAction;
  }, [onOverlayAction]);

  useEffect(() => {
    onAmendRef.current = onTicketAmend;
  }, [onTicketAmend]);

  useEffect(() => {
    onPlaceRef.current = onTicketPlace;
  }, [onTicketPlace]);

  useEffect(() => {
    livePriceRef.current = livePrice;
    placeRef.current?.setLivePrice(livePrice);
  }, [livePrice]);

  useEffect(() => {
    priceDecimalsRef.current = priceDecimals;
    amendRef.current?.setPriceDecimals(priceDecimals);
    placeRef.current?.setPriceDecimals(priceDecimals);
  }, [priceDecimals]);

  useEffect(() => {
    axisArmedRef.current = axisArmed;
    placeRef.current?.setArmed(axisArmed);
    if (!axisArmed) {
      ghostRef.current = null;
    }
  }, [axisArmed]);

  useEffect(() => {
    volOnRef.current = volOn;
  }, [volOn]);

  useEffect(() => {
    topRef.current = top;
  }, [top]);

  useEffect(() => {
    bboOnRef.current = bboOn;
  }, [bboOn]);

  useEffect(() => {
    if (!isPrice || fromSeconds) return;
    const key = `${symbol}:${bar.label}`;
    const source = candleSource(bar);
    let cancelled = false;
    api
      .candles(symbol, source, 500)
      .then((data) => {
        if (cancelled) return;
        const candles = source === bar.label ? data : aggregateCandles(data, bar.seconds);
        setHist({ key, candles });
      })
      .catch(() => {
        if (!cancelled) setHist({ key, candles: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, bar, fromSeconds, isPrice]);

  useEffect(() => {
    if (!isPrice || !fromSeconds) return;
    let cancelled = false;
    api
      .candles(symbol, "1s", 3600)
      .then((data) => {
        if (!cancelled && data.length) seedCandles1s(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [symbol, fromSeconds, isPrice]);

  useEffect(() => {
    if (!showOi) return;
    const key = `${symbol}:${tf}`;
    let cancelled = false;
    const load = () => {
      api
        .openInterest(symbol, tf, 500)
        .then((data) => {
          if (!cancelled) setOiHist({ key, points: data });
        })
        .catch(() => {
          if (!cancelled) setOiHist({ key, points: [] });
        });
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, tf, showOi]);

  useEffect(() => {
    if (!showOi) return;
    const id = setInterval(() => setNowSec(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, [showOi]);

  const display = useMemo(() => {
    if (fromSeconds) {
      return bar.seconds === 1 ? candles1s : aggregateCandles(candles1s, bar.seconds);
    }
    // 1m: never drop REST history when a short live stream arrives.
    if (bar.seconds === 60) return mergeCandles(histBars, minuteCandles);
    return foldMinutes(histBars, minuteCandles, bar.seconds);
  }, [fromSeconds, bar, candles1s, minuteCandles, histBars]);

  useEffect(() => {
    if (!isPrice) return;
    if (!containerRef.current || !wrapRef.current) return;

    const wrap = wrapRef.current;
    const chart = createChart(containerRef.current, {
      width: wrap.clientWidth,
      height: wrap.clientHeight,
      layout: {
        background: { color: theme.panel },
        textColor: theme.muted,
        fontFamily: theme.fontMono,
        fontSize: theme.chartFontSize,
      },
      grid: {
        vertLines: { color: theme.rule },
        horzLines: { color: theme.rule },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: theme.rule,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: theme.rule,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: RIGHT_OFFSET,
        shiftVisibleRangeOnNewBar: true,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: theme.bid,
      downColor: theme.ask,
      borderUpColor: theme.bid,
      borderDownColor: theme.ask,
      wickUpColor: theme.bid,
      wickDownColor: theme.ask,
      priceFormat: priceFormat(priceDecimals),
    });
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    applyVolumeLayout(series, volOnRef.current);

    chartRef.current = chart;
    seriesRef.current = series;
    volSeriesRef.current = vol;
    primedRef.current = false;
    lastMetaRef.current = null;

    const tradingLines = new TradingLinesPrimitive();
    series.attachPrimitive(tradingLines);
    tradingLinesRef.current = tradingLines;

    const topOfBook = new TopOfBookPrimitive();
    series.attachPrimitive(topOfBook);
    topOfBookRef.current = topOfBook;
    topOfBook.setTop(bboOnRef.current ? topRef.current : null);

    const paintLines = () => {
      const lines: ChartOverlay[] = [];
      for (const o of overlaysRef.current) {
        if (!Number.isFinite(o.price) || o.price <= 0) continue;
        lines.push(o);
      }
      const preview = amendRef.current?.preview();
      const painted = preview
        ? lines.map((o) => (o.id === preview.overlayId ? { ...o, price: preview.price } : o))
        : lines;
      const ghost = ghostRef.current;
      tradingLines.setLines(ghost ? [...painted, ghost] : painted);
    };
    paintLinesRef.current = paintLines;

    const host: TicketAmendHost & {
      regionAt: (pt: { x: number; y: number }) => "axis" | "pane" | "elsewhere";
    } = {
      priceAtY(y) {
        const px = series.coordinateToPrice(y);
        return px != null && Number.isFinite(px) ? px : null;
      },
      setPanEnabled(enabled) {
        chart.applyOptions({ handleScroll: enabled, handleScale: enabled });
      },
      hit(pt) {
        return tradingLines.hitAt(pt.x, pt.y);
      },
      regionAt(pt) {
        return chartRegion(chart, pt);
      },
    };

    const amend = createTicketAmend(host, {
      onAmend: (a) => onAmendRef.current?.(a),
    });
    amend.setPriceDecimals(priceDecimalsRef.current);
    amend.setOverlays(overlaysRef.current);
    amendRef.current = amend;

    const place = createTicketPlace(host, {
      onPlace: (p) => onPlaceRef.current?.(p),
    });
    place.setPriceDecimals(priceDecimalsRef.current);
    place.setLivePrice(livePriceRef.current);
    place.setArmed(axisArmedRef.current);
    placeRef.current = place;

    const el = containerRef.current;
    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0 || !el) return;
      const pt = chartPoint(el, e);
      if (amend.pointerDown(pt)) {
        suppressClickRef.current = true;
        try {
          el.setPointerCapture(e.pointerId);
        } catch {
          /* ignore */
        }
        paintLines();
        return;
      }
      place.pointerDown(pt);
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!el) return;
      const pt = chartPoint(el, e);
      amend.pointerMove(pt);
      place.pointerMove(pt);
      const hover = place.hover(pt);
      ghostRef.current = hover ? axisGhost(Number(hover.price), hover.side) : null;
      const region = host.regionAt(pt);
      if (amend.preview()) el.style.cursor = "ns-resize";
      else if (axisArmedRef.current && region === "axis") el.style.cursor = "ns-resize";
      else el.style.cursor = "";
      paintLines();
    };
    const finishPointer = (e: PointerEvent) => {
      if (!el) return;
      const pt = chartPoint(el, e);
      amend.pointerUp();
      place.pointerUp(pt);
      try {
        el.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      paintLines();
    };
    const onPointerCancel = () => {
      amend.pointerCancel();
      place.pointerCancel();
      ghostRef.current = null;
      if (el) el.style.cursor = "";
      paintLines();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      amend.pointerCancel();
      place.pointerCancel();
      ghostRef.current = null;
      paintLines();
    };
    el?.addEventListener("pointerdown", onPointerDown);
    el?.addEventListener("pointermove", onPointerMove);
    el?.addEventListener("pointerup", finishPointer);
    el?.addEventListener("pointercancel", onPointerCancel);
    document.addEventListener("keydown", onKeyDown);
    paintLines();

    const onClick = (param: { hoveredInfo?: { objectId?: unknown }; hoveredObjectId?: unknown }) => {
      if (suppressClickRef.current) {
        suppressClickRef.current = false;
        return;
      }
      const action = parseOverlayAction(param.hoveredInfo?.objectId ?? param.hoveredObjectId);
      if (!action) return;
      const overlay = overlaysRef.current.find((o) => o.id === action.id);
      if (overlay) onActionRef.current?.(action, overlay);
    };
    chart.subscribeClick(onClick);

    const onMove = (param: MouseEventParams) => {
      const key = seriesKeyRef.current;
      if (!param.time) {
        setHover((h) => (h == null || h.key !== key ? h : null));
        return;
      }
      const raw = param.seriesData.get(series);
      if (raw && "open" in raw && "close" in raw) {
        const rawVol = param.seriesData.get(vol);
        const volVal =
          volOnRef.current && rawVol && "value" in rawVol
            ? (rawVol as HistogramData).value
            : undefined;
        const next = ohlcOf(raw as CandlestickData, volVal);
        const oiSeries = oiSeriesRef.current;
        const rawOi = oiSeries ? param.seriesData.get(oiSeries) : undefined;
        const oi =
          rawOi && "value" in rawOi && typeof rawOi.value === "number" && Number.isFinite(rawOi.value)
            ? rawOi.value
            : null;
        setHover((prev) => {
          if (!next) return prev?.key === key ? null : prev;
          if (prev?.key === key && sameOhlc(prev.bar, next) && prev.oi === oi) return prev;
          return { key, bar: next, oi };
        });
      }
    };
    chart.subscribeCrosshairMove(onMove);

    let lastW = wrap.clientWidth;
    let lastH = wrap.clientHeight;
    const ro = new ResizeObserver(() => {
      const el = wrapRef.current;
      if (!el) return;
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w < 1 || h < 1 || (w === lastW && h === lastH)) return;
      lastW = w;
      lastH = h;
      chart.applyOptions({ width: w, height: h });
    });
    ro.observe(wrap);

    return () => {
      ro.disconnect();
      el?.removeEventListener("pointerdown", onPointerDown);
      el?.removeEventListener("pointermove", onPointerMove);
      el?.removeEventListener("pointerup", finishPointer);
      el?.removeEventListener("pointercancel", onPointerCancel);
      document.removeEventListener("keydown", onKeyDown);
      amend.destroy();
      place.destroy();
      amendRef.current = null;
      placeRef.current = null;
      paintLinesRef.current = () => {};
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volSeriesRef.current = null;
      oiSeriesRef.current = null;
      tradingLinesRef.current = null;
      topOfBookRef.current = null;
    };
    // Recreate when returning to the price chart; format is applied below.
    // oxlint-disable-next-line exhaustive-deps
  }, [isPrice]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !showOi) {
      const series = oiSeriesRef.current;
      oiSeriesRef.current = null;
      if (series && chartRef.current) chartRef.current.removeSeries(series);
      return;
    }
    const series = chart.addSeries(
      LineSeries,
      {
        color: theme.warn,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
        priceFormat: {
          type: "custom",
          minMove: 1,
          formatter: (price: number) => formatUsdCompact(price) || "$0",
        },
      },
      1,
    );
    chart.panes()[1]?.setStretchFactor(0.28);
    oiSeriesRef.current = series;
    series.setData(oiLineRef.current);
    return () => {
      oiSeriesRef.current = null;
      if (chartRef.current) chart.removeSeries(series);
    };
  }, [showOi]);

  useEffect(() => {
    oiSeriesRef.current?.setData(oiLineRef.current);
  }, [oiShape, showOi]);

  useEffect(() => {
    const series = oiSeriesRef.current;
    const last = oiLineRef.current[oiLineRef.current.length - 1];
    if (!series || !last || !("value" in last)) return;
    series.update(last);
  }, [liveOi, nowSec, showOi]);

  useEffect(() => {
    seriesRef.current?.applyOptions({ priceFormat: priceFormat(priceDecimals) });
  }, [priceDecimals]);

  useEffect(() => {
    // Drop old bars before secondsVisible / tick regeneration — otherwise 1s ticks
    // over a 1d/4h range lock the main thread.
    seriesRef.current?.setData([]);
    volSeriesRef.current?.setData([]);
    chartRef.current?.timeScale().applyOptions({
      secondsVisible: showsSeconds(bar),
      rightOffset: RIGHT_OFFSET,
    });
    chartRef.current?.timeScale().resetTimeScale();
    primedRef.current = false;
    lastMetaRef.current = null;
  }, [symbol, tf, bar]);

  useEffect(() => {
    const tick = () => rollLiveCandles();
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible") return;
      primedRef.current = false;
      setPaintGen((n) => n + 1);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (series) applyVolumeLayout(series, volOn);
    if (!volOn) volSeriesRef.current?.setData([]);
    primedRef.current = false;
  }, [volOn]);

  useEffect(() => {
    primedRef.current = false;
  }, [mayRektOn]);

  useEffect(() => {
    const series = seriesRef.current;
    const vol = volSeriesRef.current;
    const chart = chartRef.current;
    if (!series) return;

    if (display.length === 0) {
      series.setData([]);
      vol?.setData([]);
      primedRef.current = false;
      lastMetaRef.current = null;
      return;
    }

    const { candles: rawBars, volume } = toSeriesData(display);
    const bars = mayRektOn ? stampMayRekt(rawBars, display) : rawBars;
    if (bars.length === 0) {
      series.setData([]);
      vol?.setData([]);
      primedRef.current = false;
      lastMetaRef.current = null;
      return;
    }
    const first = bars[0].time as number;
    const last = bars[bars.length - 1];
    const lastVol = volume[volume.length - 1];
    const lastT = last.time as number;
    const len = bars.length;
    const nextMeta = { first, time: lastT, len };
    const prev = lastMetaRef.current;

    if (shouldReplaceChartData(prev, nextMeta, primedRef.current)) {
      series.setData(bars);
      vol?.setData(volOn ? volume : []);
      chart?.timeScale().applyOptions({
        secondsVisible: showsSeconds(bar),
        rightOffset: RIGHT_OFFSET,
      });
      chart?.timeScale().scrollToRealTime();
      primedRef.current = true;
      lastMetaRef.current = nextMeta;
      return;
    }

    if (prev && len === prev.len + 1 && bars.length >= 2) {
      series.update(bars[bars.length - 2]);
      if (volOn && volume.length >= 2) vol?.update(volume[volume.length - 2]);
    }
    series.update(last);
    if (volOn && lastVol) vol?.update(lastVol);
    lastMetaRef.current = nextMeta;
  }, [display, tf, bar, volOn, mayRektOn, paintGen]);

  useEffect(() => {
    paintLinesRef.current();
  }, [overlays, axisArmed]);

  useEffect(() => {
    const primitive = topOfBookRef.current;
    if (!primitive) return;
    primitive.setTop(bboOn ? top : null);
  }, [top, bboOn]);

  const selectTf = (next: string) => {
    const parsed = parseTimeframe(next);
    if (!parsed || parsed.label === tf) return;
    setTf(parsed.label);
    persistTimeframe(parsed.label);
  };

  const changePins = (next: string[]) => {
    setPins(next);
    persistPins(next);
  };

  const selectMode = (next: ChartMode) => {
    if (next === mode) return;
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      /* ignore */
    }
  };

  const selectScanTab = (next: ScanTab) => {
    if (next === scanTab) return;
    setScanTab(next);
    try {
      localStorage.setItem(SCAN_TAB_KEY, next);
    } catch {
      /* ignore */
    }
  };

  const selectWatchWindow = (next: WatchWindow) => {
    if (next === watchWindow) return;
    setWatchWindow(next);
    persistWatchWindow(next);
  };

  const lastBar = display.length ? ohlcOf(display[display.length - 1]) : null;
  const ohlc = hoverBar ?? lastBar;
  const hovered = hover?.key === seriesKey ? hover : null;
  const oiRead = hovered ? hovered.oi : liveOi;
  const numeraireChange24h = useMemo(
    () => rankRelativeStrength(markets).numeraireChange24h,
    [markets]
  );

  const toggleVol = () => {
    setVolOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(VOL_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleOi = () => {
    setOiOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(OI_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleBbo = () => {
    setBboOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(BBO_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleMayRekt = () => {
    setMayRektOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(MAYREKT_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="panel-drag grid h-8 shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center border-b border-border">
        <div className="flex min-w-0 items-center gap-px overflow-hidden px-1">
          {isPrice ? (
            <>
              <Toggle
                variant="seg"
                size="sm"
                pressed={volOn}
                title={volOn ? "Hide volume" : "Show volume"}
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleVol()}
              >
                Vol
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={showOi}
                disabled={!supportsOpenInterest(bar)}
                title={
                  supportsOpenInterest(bar)
                    ? oiOn
                      ? "Hide open interest"
                      : "Show open interest"
                    : "Open interest follows 1m, 5m, 15m, 1h, 4h, and 1d"
                }
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleOi()}
              >
                OI
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={bboOn}
                title="Top of book"
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleBbo()}
              >
                B/A
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={mayRektOn}
                title={mayRektOn ? "Hide MayRekt" : "MayRekt"}
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleMayRekt()}
              >
                MR
              </Toggle>
              <span className="mx-1 h-3 w-px shrink-0 bg-border" aria-hidden />
              <Toggle
                variant="seg"
                size="sm"
                pressed={axisArmed}
                title="Rest a Ticket on the price axis at Quick size. Below live price buys, above sells."
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={(next) => setAxisArmed(next)}
              >
                Axis
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={quickOn}
                title={quickOn ? "Hide quick trade" : "Quick trade"}
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={(next) => setQuickOn(next)}
              >
                QT
              </Toggle>
            </>
          ) : isScan && scanTab === "liqs" ? (
            <LiqsReadout hours={liqHours} />
          ) : isScan ? (
            <NumeraireReadout change={numeraireChange24h} />
          ) : null}
        </div>
        <ToggleGroup
          type="single"
          size="sm"
          spacing={0}
          value={isWatch ? "watch" : mode === "scan" ? "scan" : "price"}
          className="bg-background"
          onValueChange={(v) => {
            if (v === "watch") {
              if (popped) openWatchWindow();
              else selectMode("watch");
              return;
            }
            if (v && (CHART_MODES as readonly string[]).includes(v)) {
              selectMode(v as ChartMode);
            }
          }}
        >
          <ToggleGroupItem
            value="price"
            title="Price chart"
            className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
          >
            Chart
          </ToggleGroupItem>
          <ToggleGroupItem
            value="scan"
            title="Scan: Rel vs BTC and liquidations"
            className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
          >
            Scan
          </ToggleGroupItem>
          <ToggleGroupItem
            value="watch"
            title={popped ? "Watch is in its own window" : "Watch: live percent paths"}
            className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
          >
            Watch
          </ToggleGroupItem>
        </ToggleGroup>
        <div className="flex min-w-0 items-center justify-end gap-px overflow-hidden pr-1">
          {isScan ? (
            <ToggleGroup
              type="single"
              size="sm"
              spacing={0}
              value={scanTab}
              onValueChange={(v) => {
                if (v && (SCAN_TABS as readonly string[]).includes(v)) {
                  selectScanTab(v as ScanTab);
                }
              }}
            >
              <ToggleGroupItem
                value="rel"
                title="Relative strength vs BTC"
                className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
              >
                Rel
              </ToggleGroupItem>
              <ToggleGroupItem
                value="liqs"
                title="Liquidations in window"
                className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
              >
                Liqs
              </ToggleGroupItem>
            </ToggleGroup>
          ) : null}
          {isWatch ? (
            <>
            <ToggleGroup
              type="single"
              size="sm"
              spacing={0}
              value={watchWindow}
              onValueChange={(v) => {
                if (v && (WATCH_WINDOWS as readonly string[]).includes(v)) {
                  selectWatchWindow(v as WatchWindow);
                }
              }}
            >
              {WATCH_WINDOWS.map((w) => (
                <ToggleGroupItem
                  key={w}
                  value={w}
                  title="Path window"
                  className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
                >
                  {w}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <button
              type="button"
              title="Pop out Watch"
              className="inline-flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => {
                if (openWatchWindow()) selectMode("price");
              }}
            >
              <SquareArrowOutUpRight className="size-3.5" />
            </button>
          </>
          ) : null}
          {isPrice ? (
            <TimeframePins timeframe={tf} pins={pins} onSelect={selectTf} onPins={changePins} />
          ) : null}
          {onClose ? <PanelCloseButton onClose={onClose} /> : null}
        </div>
      </div>
      <div ref={wrapRef} className="relative flex min-h-0 flex-1 flex-col">
        {isPrice ? (
          <>
            <div ref={containerRef} className="absolute inset-0" />
            <div className="pointer-events-none absolute top-1 left-1.5 z-10 max-w-[calc(100%-4.5rem)] overflow-hidden rounded-sm bg-card/90 px-1 py-0.5">
              <OhlcReadout
                bar={ohlc}
                decimals={priceDecimals}
                showVolume={volOn}
                showOi={showOi}
                oi={oiRead}
              />
            </div>
            {children ? (
              <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
                {children}
              </div>
            ) : null}
          </>
        ) : isWatch ? (
          <WatchBoard
            windowSec={WATCH_WINDOW_SEC[watchWindow]}
            markets={markets}
            symbol={symbol}
            onSymbolChange={onSymbolChange}
          />
        ) : (
          <ScanBoard
            tab={scanTab}
            hours={liqHours}
            onHoursChange={setLiqHours}
            markets={markets}
            symbol={symbol}
            onSymbolChange={onSymbolChange}
          />
        )}
      </div>
    </div>
  );
});
