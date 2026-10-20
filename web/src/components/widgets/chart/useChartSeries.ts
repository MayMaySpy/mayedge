/* oxlint-disable react-hooks/exhaustive-deps, react/immutability -- effects moved unchanged */
import {
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { useEffect, type Dispatch, type RefObject, type SetStateAction } from "react";

import type { Candle } from "@/lib/api";
import { shouldReplaceChartData, toSeriesData } from "@/lib/chartCandles";
import { showsSeconds } from "@/lib/timeframe";
import type { ChartOverlay } from "@/lib/chartTradingLines";
import { FillMarksPrimitive, type FillSpot } from "@/lib/fillMarkPrimitive";
import { formatApr, formatUsdCompact } from "@/lib/utils";
import { rollLiveCandles } from "@/lib/liveData";
import { theme } from "@/lib/theme";
import type { TopOfBookPrimitive } from "@/lib/chartTopOfBook";

import { applyVolumeLayout, priceFormat } from "./chartFormat";
import { RIGHT_OFFSET } from "./chartPrefs";
import { INDICATOR_STRETCH, reuseToneStamp, stampMayRekt } from "./chartTones";

type Bar = { label: string; seconds: number };

type SeriesInput = {
  showOi: boolean;
  showFund: boolean;
  oiShape: string;
  fundShape: string;
  liveOi: number | null;
  nowSec: number;
  liveFunding: number | null;
  priceDecimals: number;
  symbol: string;
  tf: string;
  bar: Bar;
  display: Candle[];
  volOn: boolean;
  mayRektOn: boolean;
  paintGen: number;
  setPaintGen: Dispatch<SetStateAction<number>>;
  overlays: ChartOverlay[];
  axisArmed: boolean;
  top: ReturnType<typeof import("@/lib/liveData").useLiveTopOfBook>;
  bboOn: boolean;
  chartRef: RefObject<IChartApi | null>;
  oiSeriesRef: RefObject<ISeriesApi<"Line"> | null>;
  fundSeriesRef: RefObject<ISeriesApi<"Histogram"> | null>;
  seriesRef: RefObject<ISeriesApi<"Candlestick"> | null>;
  volSeriesRef: RefObject<ISeriesApi<"Histogram"> | null>;
  oiLineRef: RefObject<import("@/lib/openInterest").OiLinePoint[]>;
  fundBarsRef: RefObject<import("@/lib/funding").FundingBar[]>;
  toneBarsRef: RefObject<import("lightweight-charts").CandlestickData[] | null>;
  toneStampAt: RefObject<number>;
  primedRef: RefObject<boolean>;
  lastMetaRef: RefObject<{ first: number; time: number; len: number } | null>;
  fillMarksRef: RefObject<FillMarksPrimitive | null>;
  fillSpotRef: RefObject<FillSpot[]>;
  paintLinesRef: RefObject<() => void>;
  topOfBookRef: RefObject<TopOfBookPrimitive | null>;
};

export function useChartSeries(input: SeriesInput) {
  const {
    showOi, showFund, oiShape, fundShape, liveOi, nowSec, liveFunding,
    priceDecimals, symbol, tf, bar, display, volOn, mayRektOn, paintGen, setPaintGen,
    overlays, axisArmed, top, bboOn,
    chartRef, oiSeriesRef, fundSeriesRef, seriesRef, volSeriesRef,
    oiLineRef, fundBarsRef, toneBarsRef, toneStampAt, primedRef, lastMetaRef,
    fillMarksRef, fillSpotRef, paintLinesRef, topOfBookRef,
  } = input;
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
    chart.panes()[1]?.setStretchFactor(INDICATOR_STRETCH);
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

  // Below OI when both are on. Rebuilt when OI toggles, since an empty pane is dropped.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !showFund) {
      const series = fundSeriesRef.current;
      fundSeriesRef.current = null;
      if (series && chartRef.current) chartRef.current.removeSeries(series);
      return;
    }
    const pane = showOi ? 2 : 1;
    const series = chart.addSeries(
      HistogramSeries,
      {
        priceLineVisible: false,
        lastValueVisible: true,
        base: 0,
        priceFormat: {
          type: "custom",
          minMove: 0.01,
          formatter: (apr: number) => formatApr(apr),
        },
      },
      pane,
    );
    series.createPriceLine({
      price: 0,
      color: theme.rule,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: false,
    });
    chart.panes()[pane]?.setStretchFactor(INDICATOR_STRETCH);
    fundSeriesRef.current = series;
    series.setData(fundBarsRef.current);
    return () => {
      fundSeriesRef.current = null;
      if (chartRef.current) chart.removeSeries(series);
    };
  }, [showFund, showOi]);

  useEffect(() => {
    fundSeriesRef.current?.setData(fundBarsRef.current);
  }, [fundShape, showFund, showOi]);

  useEffect(() => {
    const series = fundSeriesRef.current;
    const last = fundBarsRef.current[fundBarsRef.current.length - 1];
    if (!series || !last || !("value" in last)) return;
    series.update(last);
  }, [liveFunding, nowSec, showFund]);

  useEffect(() => {
    seriesRef.current?.applyOptions({ priceFormat: priceFormat(priceDecimals) });
  }, [priceDecimals]);

  useEffect(() => {
    // Drop old bars before secondsVisible / tick regeneration — otherwise 1s ticks
    // over a 1d/4h range lock the main thread.
    seriesRef.current?.setData([]);
    volSeriesRef.current?.setData([]);
    toneBarsRef.current = null;
    toneStampAt.current = 0;
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
    toneBarsRef.current = null;
    toneStampAt.current = 0;
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
    let bars = rawBars;
    if (mayRektOn) {
      const now = performance.now();
      const reused = reuseToneStamp(toneBarsRef.current, rawBars, toneStampAt.current, now);
      if (reused) {
        bars = reused;
        toneBarsRef.current = reused;
      } else {
        bars = stampMayRekt(rawBars, display);
        toneBarsRef.current = bars;
        toneStampAt.current = now;
      }
    }
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
      fillMarksRef.current?.setMarks(fillSpotRef.current);
      return;
    }

    if (prev && len === prev.len + 1 && bars.length >= 2) {
      series.update(bars[bars.length - 2]);
      if (volOn && volume.length >= 2) vol?.update(volume[volume.length - 2]);
    }
    series.update(last);
    if (volOn && lastVol) vol?.update(lastVol);
    lastMetaRef.current = nextMeta;
    fillMarksRef.current?.setMarks(fillSpotRef.current);
  }, [display, tf, bar, volOn, mayRektOn, paintGen]);

  useEffect(() => {
    paintLinesRef.current();
  }, [overlays, axisArmed]);

  useEffect(() => {
    const primitive = topOfBookRef.current;
    if (!primitive) return;
    primitive.setTop(bboOn ? top : null);
  }, [top, bboOn]);
}
