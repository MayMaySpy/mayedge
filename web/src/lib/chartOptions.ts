import { ColorType, CrosshairMode, type DeepPartial, type TimeChartOptions } from "lightweight-charts";
import { theme } from "@/lib/theme";

type Options = DeepPartial<TimeChartOptions>;

const FONT = {
  textColor: theme.muted,
  fontFamily: theme.fontMono,
  fontSize: theme.chartFontSize,
};

/** A live market chart: panel background, rules both ways, a free crosshair. */
export function liveChartOptions({
  width,
  height,
  rightPriceScale,
  timeScale,
}: {
  width: number;
  height: number;
  rightPriceScale?: Options["rightPriceScale"];
  timeScale?: Options["timeScale"];
}): Options {
  return {
    width,
    height,
    localization: { locale: theme.chartLocale },
    layout: { background: { color: theme.panel }, ...FONT },
    grid: { vertLines: { color: theme.rule }, horzLines: { color: theme.rule } },
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: { borderColor: theme.rule, ...rightPriceScale },
    timeScale: {
      borderColor: theme.rule,
      timeVisible: true,
      shiftVisibleRangeOnNewBar: true,
      ...timeScale,
    },
  };
}

/** A small summary chart that does not scroll or zoom: no background, rules across only. */
export function summaryChartOptions({
  height,
  priceFormatter,
  rightPriceScale,
  timeScale,
}: {
  /** Omit to fill the parent. */
  height?: number;
  priceFormatter: (v: number) => string;
  rightPriceScale?: Options["rightPriceScale"];
  timeScale?: Options["timeScale"];
}): Options {
  return {
    ...(height == null ? {} : { height }),
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: "transparent" }, ...FONT },
    grid: { vertLines: { visible: false }, horzLines: { color: theme.rule } },
    localization: { locale: theme.chartLocale, priceFormatter },
    rightPriceScale: { borderVisible: false, ...rightPriceScale },
    timeScale: { borderVisible: false, ...timeScale },
    handleScroll: false,
    handleScale: false,
  };
}
