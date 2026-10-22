import type {
  IChartApiBase,
  ISeriesApi,
  ISeriesPrimitiveAxisView,
  SeriesAttachedParameter,
  SeriesType,
} from "lightweight-charts";
import { theme } from "@/lib/theme";

let measureCtx: CanvasRenderingContext2D | null = null;

/** Width of `text` in `font`, from one shared offscreen canvas. */
export function measureText(text: string, font: string): number {
  if (!measureCtx) {
    const c = document.createElement("canvas");
    measureCtx = c.getContext("2d");
  }
  if (!measureCtx) return text.length * 6.6;
  measureCtx.font = font;
  return measureCtx.measureText(text).width;
}

/** The series and chart a primitive is attached to, and its redraw request. */
export class AttachedPrimitive {
  protected _series: ISeriesApi<SeriesType> | undefined;
  protected _chart: IChartApiBase<unknown> | undefined;
  protected _requestUpdate: (() => void) | undefined;

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

  chart() {
    return this._chart;
  }

  paneWidth() {
    try {
      return this._chart?.paneSize()?.width ?? 0;
    } catch {
      return 0;
    }
  }
}

export type AxisLevel = { series: ISeriesApi<SeriesType>; price: number; color: string };

/** A price label on the right axis, pinned to the price `read` returns, or hidden on null. */
export class PriceAxisLabel implements ISeriesPrimitiveAxisView {
  private _read: () => AxisLevel | null;
  private _y = 0;
  private _visible = false;
  private _text = "";
  private _color: string = theme.muted;

  constructor(read: () => AxisLevel | null) {
    this._read = read;
  }

  update() {
    const level = this._read();
    const y = level ? level.series.priceToCoordinate(level.price) : null;
    if (!level || y == null) {
      this._visible = false;
      return;
    }
    this._y = y;
    this._visible = true;
    this._color = level.color;
    this._text = level.series.priceFormatter().format(level.price);
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
