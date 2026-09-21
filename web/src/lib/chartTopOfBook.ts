import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  SeriesAttachedParameter,
  SeriesType,
} from "lightweight-charts";
import type { TopOfBook } from "@/lib/liveData";
import { theme } from "@/lib/theme";
import { formatSize } from "@/lib/utils";

const FONT = `${theme.chartFontSize}px ${theme.fontMono}`;
const LINE_ALPHA = 0.7;
const MIN_LABEL_GAP = 12;
const SIZE_H = 16;
const SIZE_PAD_X = 4;
const RIGHT = 6;
const SIZE_BG = "rgba(16, 22, 31, 0.75)";

/** Separate overlapping Best Bid / Best Ask size labels. Bid stays below ask on screen. */
export function stackSizeLabels(
  bidY: number,
  askY: number,
  minGap: number
): { bidY: number; askY: number } {
  if (Math.abs(bidY - askY) >= minGap) return { bidY, askY };
  const mid = (bidY + askY) / 2;
  const half = minGap / 2;
  return { bidY: mid + half, askY: mid - half };
}

type Side = "bid" | "ask";

type SideGeom = {
  y: number;
  labelY: number;
  sizeText: string;
  color: string;
};

let measureCtx: CanvasRenderingContext2D | null = null;

function measure(text: string, font: string): number {
  if (!measureCtx) {
    const c = document.createElement("canvas");
    measureCtx = c.getContext("2d");
  }
  if (!measureCtx) return text.length * 6.6;
  measureCtx.font = font;
  return measureCtx.measureText(text).width;
}

function sideColor(side: Side): string {
  return side === "bid" ? theme.bid : theme.ask;
}

function parseLevel(level: { price: string; size: string } | null): {
  price: number;
  sizeText: string;
} | null {
  if (!level) return null;
  const price = parseFloat(level.price);
  if (!Number.isFinite(price) || price <= 0) return null;
  const sizeText = formatSize(level.size);
  if (sizeText === "—") return null;
  return { price, sizeText };
}

class PriceAxisLabel implements ISeriesPrimitiveAxisView {
  private _source: TopOfBookPrimitive;
  private _side: Side;
  private _y = 0;
  private _visible = false;
  private _text = "";
  private _color: string = theme.muted;

  constructor(source: TopOfBookPrimitive, side: Side) {
    this._source = source;
    this._side = side;
  }

  update() {
    const series = this._source.series();
    const level = this._source.top()?.[this._side] ?? null;
    const parsed = parseLevel(level);
    if (!series || !parsed) {
      this._visible = false;
      return;
    }
    const y = series.priceToCoordinate(parsed.price);
    if (y == null) {
      this._visible = false;
      return;
    }
    this._y = y;
    this._visible = true;
    this._color = sideColor(this._side);
    this._text = series.priceFormatter().format(parsed.price);
  }

  coordinate() {
    return -10000;
  }

  fixedCoordinate() {
    return this._y;
  }

  text() {
    return this._text;
  }

  textColor() {
    return "#ffffff";
  }

  backColor() {
    return this._color;
  }

  visible() {
    return this._visible;
  }

  tickVisible() {
    return this._visible;
  }
}

class PaneRenderer implements IPrimitivePaneRenderer {
  private _geoms: SideGeom[];
  private _paneW: number;

  constructor(geoms: SideGeom[], paneW: number) {
    this._geoms = geoms;
    this._paneW = paneW;
  }

  draw(target: CanvasRenderingTarget2D) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const vr = scope.verticalPixelRatio;
      for (const g of this._geoms) {
        const y = Math.round(g.y * vr);
        ctx.strokeStyle = g.color;
        ctx.globalAlpha = LINE_ALPHA;
        ctx.lineWidth = Math.max(1, Math.round(vr));
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(0, y + (ctx.lineWidth % 2 ? 0.5 : 0));
        ctx.lineTo(scope.bitmapSize.width, y + (ctx.lineWidth % 2 ? 0.5 : 0));
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    });

    target.useMediaCoordinateSpace((scope) => {
      const ctx = scope.context;
      const paneW = this._paneW;
      if (paneW <= 0) return;
      ctx.font = FONT;
      ctx.textBaseline = "middle";
      ctx.textAlign = "right";
      for (const g of this._geoms) {
        const textW = measure(g.sizeText, FONT);
        const w = textW + SIZE_PAD_X * 2;
        const x = paneW - RIGHT - w;
        const y = g.labelY - SIZE_H / 2;
        ctx.beginPath();
        ctx.roundRect(x, y, w, SIZE_H, 2);
        ctx.fillStyle = SIZE_BG;
        ctx.fill();
        ctx.fillStyle = g.color;
        ctx.fillText(g.sizeText, paneW - RIGHT - SIZE_PAD_X, g.labelY);
      }
    });
  }
}

class PaneView implements IPrimitivePaneView {
  private _source: TopOfBookPrimitive;
  private _geoms: SideGeom[] = [];

  constructor(source: TopOfBookPrimitive) {
    this._source = source;
  }

  zOrder() {
    return "normal" as const;
  }

  update() {
    const series = this._source.series();
    const top = this._source.top();
    const geoms: SideGeom[] = [];
    if (!series || !top) {
      this._geoms = [];
      return;
    }
    const bid = parseLevel(top.bid);
    const ask = parseLevel(top.ask);
    const bidY = bid ? series.priceToCoordinate(bid.price) : null;
    const askY = ask ? series.priceToCoordinate(ask.price) : null;
    let bidLabelY: number | null = bidY;
    let askLabelY: number | null = askY;
    if (bidY != null && askY != null) {
      const stacked = stackSizeLabels(bidY, askY, MIN_LABEL_GAP);
      bidLabelY = stacked.bidY;
      askLabelY = stacked.askY;
    }
    if (bid && bidY != null && bidLabelY != null) {
      geoms.push({
        y: bidY,
        labelY: bidLabelY,
        sizeText: bid.sizeText,
        color: sideColor("bid"),
      });
    }
    if (ask && askY != null && askLabelY != null) {
      geoms.push({
        y: askY,
        labelY: askLabelY,
        sizeText: ask.sizeText,
        color: sideColor("ask"),
      });
    }
    this._geoms = geoms;
  }

  renderer() {
    return new PaneRenderer(this._geoms, this._source.paneWidth());
  }
}

export class TopOfBookPrimitive implements ISeriesPrimitive {
  private _series: ISeriesApi<SeriesType> | undefined;
  private _chart: IChartApiBase<unknown> | undefined;
  private _requestUpdate: (() => void) | undefined;
  private _top: TopOfBook | null = null;
  private readonly _paneView = new PaneView(this);
  private readonly _priceAxisViews = [
    new PriceAxisLabel(this, "bid"),
    new PriceAxisLabel(this, "ask"),
  ];

  attached(param: SeriesAttachedParameter) {
    this._series = param.series;
    this._chart = param.chart as IChartApiBase<unknown>;
    this._requestUpdate = param.requestUpdate;
    this._requestUpdate();
  }

  detached() {
    this._series = undefined;
    this._chart = undefined;
    this._requestUpdate = undefined;
  }

  series() {
    return this._series;
  }

  paneWidth() {
    try {
      return this._chart?.paneSize()?.width ?? 0;
    } catch {
      return 0;
    }
  }

  top() {
    return this._top;
  }

  setTop(top: TopOfBook | null) {
    this._top = top;
    this._requestUpdate?.();
  }

  updateAllViews() {
    this._paneView.update();
    for (const v of this._priceAxisViews) v.update();
  }

  paneViews() {
    return [this._paneView];
  }

  priceAxisViews() {
    return this._priceAxisViews;
  }
}
