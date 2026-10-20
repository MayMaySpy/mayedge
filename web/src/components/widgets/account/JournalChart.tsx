import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type MouseEventParams,
  type UTCTimestamp,
} from "lightweight-charts";
import { money, pnlClass } from "@/lib/journalFormat";
import { theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

type Day = { time: number; net: number };

function dayLabel(time: number): string {
  return new Date(time * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

/**
 * Daily bars and the running total. `time` is the day's start, seconds. Hovering a day
 * reads out its value and the running total; with no hover, the last day.
 */
export function JournalChart({
  days,
  height = 120,
  label = "Net",
}: {
  days: Day[];
  height?: number;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const running = useMemo(
    () => days.reduce<number[]>((acc, day) => [...acc, (acc.at(-1) ?? 0) + day.net], []),
    [days],
  );

  useEffect(() => {
    const el = ref.current;
    if (!el || days.length === 0) return;
    const chart = createChart(el, {
      height,
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
    const onMove = (param: MouseEventParams) => {
      const time = typeof param.time === "number" ? param.time : null;
      setHover(time == null ? null : days.findIndex((day) => day.time === time));
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [days, height]);

  const at = hover != null && hover >= 0 ? hover : days.length - 1;
  const day = days[at];
  return (
    <div className="flex flex-col gap-0.5">
      {day ? (
        <div className="flex items-baseline gap-3 px-2 font-mono text-sm tabular-nums" aria-live="polite">
          <span className="text-muted-foreground">{dayLabel(day.time)}</span>
          <span>
            <span className="text-muted-foreground">{label} </span>
            <span className={pnlClass(String(day.net))}>{money(String(day.net))}</span>
          </span>
          <span>
            <span className="text-muted-foreground">Running </span>
            <span className={cn(pnlClass(String(running[at])))}>{money(String(running[at]))}</span>
          </span>
        </div>
      ) : null}
      <div ref={ref} className="w-full" style={{ height }} />
    </div>
  );
}
