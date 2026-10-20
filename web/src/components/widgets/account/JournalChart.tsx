import { useEffect, useRef } from "react";
import {
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type UTCTimestamp,
} from "lightweight-charts";
import { theme } from "@/lib/theme";

/** Daily Net bars and the running Net line. `time` is UTC midnight, seconds. */
export function JournalChart({ days }: { days: { time: number; net: number }[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || days.length === 0) return;
    const chart = createChart(el, {
      height: 120,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: theme.muted,
        fontFamily: theme.fontMono,
        fontSize: theme.chartFontSize,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.rule } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    const bars = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const line = chart.addSeries(LineSeries, {
      color: theme.text,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    let run = 0;
    bars.setData(
      days.map((day) => ({
        time: day.time as UTCTimestamp,
        value: day.net,
        color: day.net >= 0 ? theme.bid : theme.ask,
      })),
    );
    line.setData(
      days.map((day) => {
        run += day.net;
        return { time: day.time as UTCTimestamp, value: run };
      }),
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [days]);

  return <div ref={ref} className="h-[120px] w-full" />;
}
