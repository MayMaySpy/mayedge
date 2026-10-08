import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
} from "lightweight-charts";
import { theme } from "@/lib/theme";

const RADIUS = 7;
const GAP = 4;

export type FillSpot = {
  time: number;
  side: "buy" | "sell";
  high: number;
  low: number;
};

type Geom = { x: number; y: number; letter: "B" | "S"; color: string };

class PaneRenderer implements IPrimitivePaneRenderer {
  private _geoms: Geom[];

  constructor(geoms: Geom[]) {
    this._geoms = geoms;
  }

  draw(target: CanvasRenderingTarget2D) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const hr = scope.horizontalPixelRatio;
      const vr = scope.verticalPixelRatio;
      const r = RADIUS * hr;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = `600 ${Math.round(9 * hr)}px ${theme.fontMono}`;
      for (const g of this._geoms) {
        const x = Math.round(g.x * hr);
        const y = Math.round(g.y * vr);
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = g.color;
        ctx.fill();
        ctx.fillStyle = theme.canvas;
        ctx.fillText(g.letter, x, y + vr * 0.5);
      }
    });
  }
}

class PaneView implements IPrimitivePaneView {
  private _source: FillMarksPrimitive;
  private _geoms: Geom[] = [];

  constructor(source: FillMarksPrimitive) {
    this._source = source;
  }

  zOrder() {
    return "top" as const;
  }

  update() {
    const series = this._source.series();
    const chart = this._source.chart();
    const geoms: Geom[] = [];
    if (!series || !chart) {
      this._geoms = [];
      return;
    }
    const scale = chart.timeScale();
    for (const mark of this._source.marks()) {
      const x = scale.timeToCoordinate(mark.time);
      const anchor = mark.side === "buy" ? mark.low : mark.high;
      const yPrice = series.priceToCoordinate(anchor);
      if (x == null || yPrice == null) continue;
      const buy = mark.side === "buy";
      geoms.push({
        x,
        y: buy ? yPrice + RADIUS + GAP : yPrice - RADIUS - GAP,
        letter: buy ? "B" : "S",
        color: buy ? theme.bid : theme.ask,
      });
    }
    this._geoms = geoms;
  }

  renderer() {
    return new PaneRenderer(this._geoms);
  }
}

export class FillMarksPrimitive implements ISeriesPrimitive {
  private _series: ISeriesApi<SeriesType> | undefined;
  private _chart: IChartApiBase<unknown> | undefined;
  private _requestUpdate: (() => void) | undefined;
  private _marks: FillSpot[] = [];
  private readonly _paneView = new PaneView(this);

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

  marks() {
    return this._marks;
  }

  updateAllViews() {
    this._paneView.update();
  }

  paneViews() {
    return [this._paneView];
  }

  setMarks(marks: FillSpot[]) {
    this._marks = marks;
    this._requestUpdate?.();
  }
}
