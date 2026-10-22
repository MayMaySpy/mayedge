import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, LineStyle, createChart, type ISeriesApi } from "lightweight-charts";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, type Market } from "@/lib/api";
import type { Idea } from "@/lib/api.gen";
import { toSeriesData } from "@/lib/chartCandles";
import { liveChartOptions } from "@/lib/chartOptions";
import { marketLast } from "@/lib/ideas";
import { theme } from "@/lib/theme";

const TF_KEY = "mayedge-idea-chart-tf";
const TFS = ["1h", "4h", "1d"] as const;
type Tf = (typeof TFS)[number];

function loadTf(): Tf {
  try {
    const raw = localStorage.getItem(TF_KEY);
    if (raw === "1h" || raw === "4h" || raw === "1d") return raw;
  } catch {
    /* ignore */
  }
  return "4h";
}

function saveTf(tf: Tf) {
  try {
    localStorage.setItem(TF_KEY, tf);
  } catch {
    /* ignore */
  }
}

type Bar = ReturnType<typeof toSeriesData>["candles"][number];

/** Candles for the Idea's Market, with the Plan drawn on them. The 10s tick updates the last bar only. */
export function IdeaChart({
  idea,
  market,
  onOpenDesk,
}: {
  idea: Idea;
  market: Market | undefined;
  onOpenDesk: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const barsRef = useRef<Bar[]>([]);
  const [tf, setTf] = useState<Tf>(loadTf);
  const planKey = `${idea.entry_low}|${idea.entry_high}|${idea.stop}|${idea.targets.map((t) => t.price).join(",")}`;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let dead = false;
    let chart: ReturnType<typeof createChart> | null = null;
    let observer: ResizeObserver | null = null;
    barsRef.current = [];
    seriesRef.current = null;
    void api.candles(idea.symbol, tf, 150).then((candles) => {
      if (dead || !ref.current) return;
      const width = Math.max(ref.current.clientWidth, 320);
      chart = createChart(
        ref.current,
        liveChartOptions({
          width,
          height: 220,
          timeScale: { timeVisible: tf !== "1d" },
        }),
      );
      const fit = () => {
        const next = ref.current?.clientWidth ?? 0;
        if (chart && next > 0) chart.applyOptions({ width: next });
      };
      observer = new ResizeObserver(fit);
      observer.observe(ref.current);
      const series = chart.addSeries(CandlestickSeries, {
        upColor: theme.bid,
        downColor: theme.ask,
        borderUpColor: theme.bid,
        borderDownColor: theme.ask,
        wickUpColor: theme.bid,
        wickDownColor: theme.ask,
        priceLineVisible: false,
      });
      const bars = toSeriesData(candles).candles;
      series.setData(bars);
      barsRef.current = bars;
      seriesRef.current = series;
      const zone = idea.side === "short" ? theme.ask : theme.bid;
      const line = (price: string | null, title: string, color: string) => {
        const n = Number(price);
        if (!(n > 0)) return;
        series.createPriceLine({
          price: n,
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          title,
          axisLabelVisible: true,
        });
      };
      if (idea.entry_low && idea.entry_low !== idea.entry_high) line(idea.entry_low, "", zone);
      line(idea.entry_high ?? idea.entry_low, "ZONE", zone);
      line(idea.stop, "STOP", theme.ask);
      idea.targets.forEach((target, i) => line(target.price, `T${i + 1}`, theme.bid));
      chart.timeScale().fitContent();
    }).catch(() => undefined);
    return () => {
      dead = true;
      observer?.disconnect();
      seriesRef.current = null;
      chart?.remove();
    };
  }, [idea.symbol, idea.side, idea.entry_low, idea.entry_high, idea.stop, idea.targets, planKey, tf]);

  useEffect(() => {
    const series = seriesRef.current;
    const bars = barsRef.current;
    const last = marketLast(market);
    if (!series || last == null || bars.length === 0) return;
    const bar = bars[bars.length - 1];
    const next = { ...bar, close: last, high: Math.max(bar.high, last), low: Math.min(bar.low, last) };
    bars[bars.length - 1] = next;
    series.update(next);
  }, [market]);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <ToggleGroup
          type="single"
          value={tf}
          onValueChange={(value) => {
            if (value === "1h" || value === "4h" || value === "1d") {
              setTf(value);
              saveTf(value);
            }
          }}
        >
          {TFS.map((item) => (
            <ToggleGroupItem key={item} value={item} className="h-6 px-2 font-mono text-xs">
              {item}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Button type="button" variant="ghost" size="sm" className="h-6" onClick={onOpenDesk}>
          Open on desk
        </Button>
      </div>
      <div ref={ref} className="h-[220px] w-full overflow-hidden" />
    </div>
  );
}
