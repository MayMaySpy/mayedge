import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
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
import { WatchBoard } from "@/components/widgets/WatchBoard";
import { api, type Candle, type LiquidationSummaryHours, type Market } from "@/lib/api";
import { openWatchWindow, useWatchPopped } from "@/lib/deskBridge";
import { rankRelativeStrength } from "@/lib/relativeStrength";
import {
  foldMinutes,
  formatBarVolume,
  mergeCandles,
  shouldReplaceChartData,
  toSeriesData,
} from "@/lib/chartCandles";
import {
  parseOverlayAction,
  TradingLinesPrimitive,
  type ChartOverlay,
  type OverlayAction,
} from "@/lib/chartTradingLines";
import { TopOfBookPrimitive } from "@/lib/chartTopOfBook";
import { useAxisTicket } from "@/lib/axisTicket";
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
  useLiveTopOfBook,
} from "@/lib/liveData";
import { theme } from "@/lib/theme";
import { cn, formatPct, formatPrice, formatSize } from "@/lib/utils";
import {
  WATCH_WINDOWS,
  WATCH_WINDOW_SEC,
  loadWatchWindow,
  persistWatchWindow,
  type WatchWindow,
} from "@/lib/watchWindow";
import { SquareArrowOutUpRight } from "lucide-react";

export type { ChartOverlay, OverlayAction, TicketAmend, TicketPlace };

const TIMEFRAMES = ["1s", "1m", "5m", "15m", "1h", "4h", "1d"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const TF_KEY = "mayedge-chart-tf";
const VOL_KEY = "mayedge-chart-vol";
const BBO_KEY = "mayedge-chart-bbo";
const MODE_KEY = "mayedge-chart-mode";
const SCAN_TAB_KEY = "mayedge-scan-tab";
const RIGHT_OFFSET = 8;

const CHART_MODES = ["price", "scan", "watch"] as const;
type ChartMode = (typeof CHART_MODES)[number];
const SCAN_TABS = ["rel", "liqs"] as const;

const TF_SECONDS: Record<Exclude<Timeframe, "1s">, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

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

function priceFormat(decimals: number) {
  const d = Math.max(0, Math.min(8, Math.floor(decimals)));
  return {
    type: "price" as const,
    precision: d,
    minMove: d === 0 ? 1 : 10 ** -d,
  };
}

function loadTf(): Timeframe {
  try {
    const raw = localStorage.getItem(TF_KEY);
    if (raw && (TIMEFRAMES as readonly string[]).includes(raw)) return raw as Timeframe;
  } catch {
    /* ignore */
  }
  return "1m";
}

function loadVol(): boolean {
  try {
    return localStorage.getItem(VOL_KEY) === "1";
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
}: {
  bar: Ohlc | null;
  decimals: number;
  showVolume?: boolean;
}) {
  if (!bar) {
    return <span className="font-mono text-[11px] text-muted-foreground">—</span>;
  }
  const up = bar.close >= bar.open;
  const tone = up ? "text-bid" : "text-ask";
  const chg = bar.open !== 0 ? ((bar.close - bar.open) / bar.open) * 100 : null;
  return (
    <span className="flex min-w-0 items-baseline gap-2 overflow-hidden font-mono text-[11px] tabular-nums">
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

function LiqsReadout({ hours }: { hours: LiquidationSummaryHours }) {
  return (
    <span className="font-mono text-[11px] text-muted-foreground tabular-nums">{hours}h liqs</span>
  );
}

function NumeraireReadout({ change }: { change: number | null }) {
  if (change == null) {
    return <span className="font-mono text-[11px] text-muted-foreground">BTC 24h —</span>;
  }
  const tone = change > 0 ? "text-bid" : change < 0 ? "text-ask" : "text-muted-foreground";
  return (
    <span className="flex min-w-0 items-baseline gap-2 overflow-hidden font-mono text-[11px] tabular-nums">
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
  const [tf, setTf] = useState<Timeframe>(loadTf);
  const [volOn, setVolOn] = useState(loadVol);
  const [bboOn, setBboOn] = useState(loadBbo);
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
  const [hover, setHover] = useState<{ key: string; bar: Ohlc } | null>(null);
  const candles1s = useLiveCandles1s(isPrice && tf === "1s");
  const minuteCandles = useLiveMinuteCandles();
  const top = useLiveTopOfBook();
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
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
  const axisArmedRef = useRef(axisArmed);
  const volOnRef = useRef(volOn);
  const primedRef = useRef(false);
  const lastMetaRef = useRef<{ first: number; time: number; len: number } | null>(null);
  const [paintGen, setPaintGen] = useState(0);
  const seriesKey = `${symbol}:${tf}`;
  const seriesKeyRef = useRef(seriesKey);
  const histBars = hist.key === seriesKey ? hist.candles : EMPTY_CANDLES;
  const hoverBar = hover?.key === seriesKey ? hover.bar : null;

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
    if (!isPrice || tf === "1s") return;
    const key = `${symbol}:${tf}`;
    let cancelled = false;
    api
      .candles(symbol, tf, 500)
      .then((data) => {
        if (!cancelled) setHist({ key, candles: data });
      })
      .catch(() => {
        if (!cancelled) setHist({ key, candles: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, tf, isPrice]);

  useEffect(() => {
    if (!isPrice || tf !== "1s") return;
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
  }, [symbol, tf, isPrice]);

  const display = useMemo(() => {
    if (tf === "1s") return candles1s;
    // 1m: never drop REST history when a short live stream arrives.
    if (tf === "1m") return mergeCandles(histBars, minuteCandles);
    return foldMinutes(histBars, minuteCandles, TF_SECONDS[tf]);
  }, [tf, candles1s, minuteCandles, histBars]);

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
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 11,
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
        setHover((prev) => {
          if (!next) return prev?.key === key ? null : prev;
          if (prev?.key === key && sameOhlc(prev.bar, next)) return prev;
          return { key, bar: next };
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
      tradingLinesRef.current = null;
      topOfBookRef.current = null;
    };
    // Recreate when returning to the price chart; format is applied below.
    // oxlint-disable-next-line exhaustive-deps
  }, [isPrice]);

  useEffect(() => {
    seriesRef.current?.applyOptions({ priceFormat: priceFormat(priceDecimals) });
  }, [priceDecimals]);

  useEffect(() => {
    // Drop old bars before secondsVisible / tick regeneration — otherwise 1s ticks
    // over a 1d/4h range lock the main thread.
    seriesRef.current?.setData([]);
    volSeriesRef.current?.setData([]);
    chartRef.current?.timeScale().applyOptions({
      secondsVisible: tf === "1s",
      rightOffset: RIGHT_OFFSET,
    });
    chartRef.current?.timeScale().resetTimeScale();
    primedRef.current = false;
    lastMetaRef.current = null;
  }, [symbol, tf]);

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

    const { candles: bars, volume } = toSeriesData(display);
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
        secondsVisible: tf === "1s",
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
  }, [display, tf, volOn, paintGen]);

  useEffect(() => {
    paintLinesRef.current();
  }, [overlays, axisArmed]);

  useEffect(() => {
    const primitive = topOfBookRef.current;
    if (!primitive) return;
    primitive.setTop(bboOn ? top : null);
  }, [top, bboOn]);

  const selectTf = (next: Timeframe) => {
    if (next === tf) return;
    setTf(next);
    try {
      localStorage.setItem(TF_KEY, next);
    } catch {
      /* ignore */
    }
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative flex h-8 shrink-0 items-center border-b border-border">
        <div className="panel-drag z-1 flex min-w-0 flex-1 cursor-move items-center gap-2 overflow-hidden px-2">
          {isPrice ? (
            <OhlcReadout bar={ohlc} decimals={priceDecimals} showVolume={volOn} />
          ) : isScan && scanTab === "liqs" ? (
            <LiqsReadout hours={liqHours} />
          ) : isScan ? (
            <NumeraireReadout change={numeraireChange24h} />
          ) : null}
        </div>
        <div className="pointer-events-none absolute inset-0 z-2 flex items-center justify-center">
          <ToggleGroup
            type="single"
            size="sm"
            spacing={0}
            value={isWatch ? "watch" : mode === "scan" ? "scan" : "price"}
            className="pointer-events-auto bg-background"
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
              className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
            >
              Chart
            </ToggleGroupItem>
            <ToggleGroupItem
              value="scan"
              title="Scan: Rel vs BTC and liquidations"
              className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
            >
              Scan
            </ToggleGroupItem>
            <ToggleGroupItem
              value="watch"
              title={popped ? "Watch is in its own window" : "Watch: live percent paths"}
              className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
            >
              Watch
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="relative z-1 flex shrink-0 items-center gap-px pr-1">
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
                className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
              >
                Rel
              </ToggleGroupItem>
              <ToggleGroupItem
                value="liqs"
                title="Liquidations in window"
                className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
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
                  className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
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
            <>
              <Toggle
                variant="seg"
                size="sm"
                pressed={volOn}
                title={volOn ? "Hide volume" : "Show volume"}
                className="h-6 px-1.5 font-mono text-[11px]"
                onPressedChange={() => toggleVol()}
              >
                Vol
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={bboOn}
                title="Top of book"
                className="h-6 px-1.5 font-mono text-[11px]"
                onPressedChange={() => toggleBbo()}
              >
                B/A
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={axisArmed}
                title="Rest a Ticket on the price axis at Quick size. Below live price buys, above sells."
                className="h-6 px-1.5 font-mono text-[11px]"
                onPressedChange={(next) => setAxisArmed(next)}
              >
                Axis
              </Toggle>
              <ToggleGroup
                type="single"
                size="sm"
                spacing={0}
                value={tf}
                onValueChange={(v) => {
                  if (v && (TIMEFRAMES as readonly string[]).includes(v)) {
                    selectTf(v as Timeframe);
                  }
                }}
              >
                {TIMEFRAMES.map((t) => (
                  <ToggleGroupItem
                    key={t}
                    value={t}
                    className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
                  >
                    {t}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </>
          ) : null}
          {onClose ? <PanelCloseButton onClose={onClose} /> : null}
        </div>
      </div>
      <div ref={wrapRef} className="relative flex min-h-0 flex-1 flex-col">
        {isPrice ? (
          <>
            <div ref={containerRef} className="absolute inset-0" />
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
