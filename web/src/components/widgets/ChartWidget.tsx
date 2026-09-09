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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { PanelCloseButton } from "@/components/desk/PanelHeader";
import { api, type Candle } from "@/lib/api";
import {
  foldMinute,
  formatBarVolume,
  mergeCandles,
  toSeriesData,
} from "@/lib/chartCandles";
import {
  parseOverlayAction,
  TradingLinesPrimitive,
  type ChartOverlay,
  type OverlayAction,
} from "@/lib/chartTradingLines";
import { seedCandles1s, useLiveCandles1s, useLiveMinuteCandles } from "@/lib/liveData";
import { theme } from "@/lib/theme";
import { cn, formatPct, formatPrice } from "@/lib/utils";

export type { ChartOverlay, OverlayAction };

const TIMEFRAMES = ["1s", "1m", "5m", "15m", "1h", "4h", "1d"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const TF_KEY = "mayedge-chart-tf";
const VOL_KEY = "mayedge-chart-vol";
const RIGHT_OFFSET = 8;

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
  onOverlayAction?: (action: OverlayAction, overlay: ChartOverlay) => void;
  onClose?: () => void;
  children?: ReactNode;
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
    return <span className="font-mono text-[11px] text-muted">—</span>;
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
          <span className="text-muted">V</span>
          <span className="text-muted">{formatBarVolume(bar.volume ?? 0)}</span>
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
      <span className="text-muted">{k}</span>
      <span className={className}>{formatPrice(v, decimals)}</span>
    </span>
  );
}

export const ChartWidget = memo(function ChartWidget({
  symbol,
  priceDecimals = 2,
  overlays = [],
  onOverlayAction,
  onClose,
  children,
}: ChartWidgetProps) {
  const [tf, setTf] = useState<Timeframe>(loadTf);
  const [volOn, setVolOn] = useState(loadVol);
  const [hist, setHist] = useState<{ key: string; candles: Candle[] }>({
    key: "",
    candles: [],
  });
  const [hover, setHover] = useState<{ key: string; bar: Ohlc } | null>(null);
  const candles1s = useLiveCandles1s(tf === "1s");
  const minuteCandles = useLiveMinuteCandles();
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const tradingLinesRef = useRef<TradingLinesPrimitive | null>(null);
  const overlaysRef = useRef(overlays);
  const onActionRef = useRef(onOverlayAction);
  const volOnRef = useRef(volOn);
  const primedRef = useRef(false);
  const firstTimeRef = useRef<number | null>(null);
  const lastMetaRef = useRef<{ time: number; len: number } | null>(null);
  const seriesKey = `${symbol}:${tf}`;
  const seriesKeyRef = useRef(seriesKey);
  const histBars = hist.key === seriesKey ? hist.candles : EMPTY_CANDLES;
  const hoverBar = hover?.key === seriesKey ? hover.bar : null;

  useEffect(() => {
    seriesKeyRef.current = seriesKey;
  }, [seriesKey]);

  useEffect(() => {
    overlaysRef.current = overlays;
  }, [overlays]);

  useEffect(() => {
    onActionRef.current = onOverlayAction;
  }, [onOverlayAction]);

  useEffect(() => {
    volOnRef.current = volOn;
  }, [volOn]);

  useEffect(() => {
    if (tf === "1s") return;
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
  }, [symbol, tf]);

  useEffect(() => {
    if (tf !== "1s") return;
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
  }, [symbol, tf]);

  const display = useMemo(() => {
    if (tf === "1s") return candles1s;
    // 1m: never drop REST history when a short live stream arrives.
    if (tf === "1m") return mergeCandles(histBars, minuteCandles);
    if (!histBars.length) return histBars;
    const lastMin = minuteCandles[minuteCandles.length - 1];
    if (!lastMin) return histBars;
    return foldMinute(histBars, lastMin, TF_SECONDS[tf]);
  }, [tf, candles1s, minuteCandles, histBars]);

  useEffect(() => {
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

    const onClick = (param: { hoveredInfo?: { objectId?: unknown }; hoveredObjectId?: unknown }) => {
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
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volSeriesRef.current = null;
      tradingLinesRef.current = null;
    };
    // Chart is created once; price format is applied in the effect below.
    // oxlint-disable-next-line exhaustive-deps
  }, []);

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
    firstTimeRef.current = null;
    lastMetaRef.current = null;
  }, [symbol, tf]);

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
      firstTimeRef.current = null;
      lastMetaRef.current = null;
      return;
    }

    const { candles: bars, volume } = toSeriesData(display);
    if (bars.length === 0) {
      series.setData([]);
      vol?.setData([]);
      primedRef.current = false;
      firstTimeRef.current = null;
      lastMetaRef.current = null;
      return;
    }
    const first = bars[0].time as number;
    const last = bars[bars.length - 1];
    const lastVol = volume[volume.length - 1];
    const lastT = last.time as number;
    const len = bars.length;
    const prev = lastMetaRef.current;

    // Full reset when history is replaced, shrinks, jumps backward, or gains many bars.
    const needsReset =
      !primedRef.current ||
      prev == null ||
      first !== firstTimeRef.current ||
      len < prev.len ||
      lastT < prev.time ||
      len > prev.len + 1;

    if (needsReset) {
      series.setData(bars);
      vol?.setData(volOn ? volume : []);
      chart?.timeScale().applyOptions({
        secondsVisible: tf === "1s",
        rightOffset: RIGHT_OFFSET,
      });
      chart?.timeScale().scrollToRealTime();
      primedRef.current = true;
      firstTimeRef.current = first;
      lastMetaRef.current = { time: lastT, len };
      return;
    }

    // Same length or +1 bar: incremental update (LWC appends when time is newer).
    series.update(last);
    if (volOn && lastVol) vol?.update(lastVol);
    lastMetaRef.current = { time: lastT, len };
  }, [display, tf, volOn]);

  useEffect(() => {
    const primitive = tradingLinesRef.current;
    if (!primitive) return;
    const lines: ChartOverlay[] = [];
    overlays.forEach((o) => {
      if (!Number.isFinite(o.price) || o.price <= 0) return;
      lines.push(o);
    });
    primitive.setLines(lines);
  }, [overlays]);

  const selectTf = (next: Timeframe) => {
    if (next === tf) return;
    setTf(next);
    try {
      localStorage.setItem(TF_KEY, next);
    } catch {
      /* ignore */
    }
  };

  const lastBar = display.length ? ohlcOf(display[display.length - 1]) : null;
  const ohlc = hoverBar ?? lastBar;

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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-7 shrink-0 items-center border-b border-rule">
        <div className="panel-drag flex min-w-0 flex-1 cursor-move items-center gap-2 px-2">
          <OhlcReadout bar={ohlc} decimals={priceDecimals} showVolume={volOn} />
        </div>
        <div className="flex shrink-0 items-center gap-px pr-1">
          <button
            type="button"
            aria-pressed={volOn}
            title={volOn ? "Hide volume" : "Show volume"}
            className={cn(
              "h-5 rounded-sm px-1.5 font-mono text-[10px]",
              volOn ? "bg-rule text-text" : "text-muted hover:text-text"
            )}
            onClick={toggleVol}
          >
            Vol
          </button>
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
          {onClose ? <PanelCloseButton onClose={onClose} /> : null}
        </div>
      </div>
      <div ref={wrapRef} className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {children ? (
          <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">{children}</div>
        ) : null}
      </div>
    </div>
  );
});
