import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  DrawingUtils,
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  SeriesAttachedParameter,
  SeriesType,
} from "lightweight-charts";
import { LineStyle } from "lightweight-charts";
import { theme } from "@/lib/theme";

export type ChartOverlayKind = "position" | "order" | "liq" | "algo" | "band";

export interface ChartOverlay {
  id: string;
  kind: ChartOverlayKind;
  price: number;
  color: string;
  label: string;
  pnl?: number;
  marketIndex?: number;
  orderIndex?: string;
  algoId?: string;
  size?: number;
  side?: "buy" | "sell";
  interactive?: boolean;
}

export type OverlayActionName = "close" | "reverse" | "cancel";

export interface OverlayAction {
  id: string;
  action: OverlayActionName;
}

const FONT = '11px "IBM Plex Mono", ui-monospace, monospace';
const PILL_H = 20;
const PAD_X = 7;
const BTN = 18;
const LEFT = 8;
/** Position pills sit near mid-pane so they don't stack on order/algo labels. */
const POSITION_X_FRAC = 0.48;
const PILL_BG = "rgba(14, 17, 22, 0.92)";
const REV_YELLOW = theme.warn;

type HitBox = {
  x: number;
  y: number;
  w: number;
  h: number;
  id: string;
  action: OverlayActionName;
};

type LineGeom = {
  line: ChartOverlay;
  y: number;
  hits: HitBox[];
  pillX: number;
  pillY: number;
  label: string;
  pnlText: string | null;
  pnlColor: string;
  showActions: boolean;
  showCancel: boolean;
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

function formatUsd(n: number): string {
  const body = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return n < 0 ? `-$${body}` : `$${body}`;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
) {
  const rad = Math.min(r, h / 2, w / 2);
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, rad);
}

function drawReverseIcon(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.fillStyle = REV_YELLOW;
  ctx.beginPath();
  ctx.moveTo(cx - 3, cy - 6);
  ctx.lineTo(cx, cy - 1);
  ctx.lineTo(cx - 6, cy - 1);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx + 3, cy + 6);
  ctx.lineTo(cx + 6, cy + 1);
  ctx.lineTo(cx, cy + 1);
  ctx.closePath();
  ctx.fill();
}

function drawCloseIcon(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.strokeStyle = theme.ask;
  ctx.lineWidth = 1.4;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(cx - 3.5, cy - 3.5);
  ctx.lineTo(cx + 3.5, cy + 3.5);
  ctx.moveTo(cx + 3.5, cy - 3.5);
  ctx.lineTo(cx - 3.5, cy + 3.5);
  ctx.stroke();
}

class PriceAxisLabel implements ISeriesPrimitiveAxisView {
  private _source: TradingLinesPrimitive;
  private _id: string;
  private _y = 0;
  private _visible = false;
  private _text = "";
  private _color: string = theme.muted;

  constructor(source: TradingLinesPrimitive, id: string) {
    this._source = source;
    this._id = id;
  }

  update() {
    const line = this._source.lineById(this._id);
    const series = this._source.series();
    if (!line || !series) {
      this._visible = false;
      return;
    }
    const y = series.priceToCoordinate(line.price);
    if (y == null) {
      this._visible = false;
      return;
    }
    this._y = y;
    this._visible = true;
    this._color = line.color;
    this._text = series.priceFormatter().format(line.price);
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
  private _geoms: LineGeom[];

  constructor(geoms: LineGeom[]) {
    this._geoms = geoms;
  }

  draw(target: CanvasRenderingTarget2D, utils?: DrawingUtils) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const hr = scope.horizontalPixelRatio;
      const vr = scope.verticalPixelRatio;
      for (const g of this._geoms) {
        const y = Math.round(g.y * vr);
        ctx.strokeStyle = g.line.color;
        ctx.lineWidth = Math.max(1, Math.round(vr));
        if (utils) {
          utils.setLineStyle(
            ctx,
            g.line.kind === "band" ? LineStyle.Dotted : LineStyle.LargeDashed
          );
        } else {
          ctx.setLineDash(
            g.line.kind === "band" ? [2 * hr, 4 * hr] : [6 * hr, 6 * hr]
          );
        }
        ctx.beginPath();
        ctx.moveTo(0, y + (ctx.lineWidth % 2 ? 0.5 : 0));
        ctx.lineTo(scope.bitmapSize.width, y + (ctx.lineWidth % 2 ? 0.5 : 0));
        ctx.stroke();
        ctx.setLineDash([]);
      }
    });

    target.useMediaCoordinateSpace((scope) => {
      const ctx = scope.context;
      for (const g of this._geoms) {
        if (g.line.kind === "band") continue;
        this._drawPill(ctx, g);
      }
    });
  }

  private _drawPill(ctx: CanvasRenderingContext2D, g: LineGeom) {
    const y = g.pillY;
    let x = g.pillX;
    const labelW = measure(g.label, FONT);
    let inner = PAD_X + labelW + PAD_X;
    if (g.pnlText) inner += 2 + measure(g.pnlText, FONT) + PAD_X;
    if (g.showActions) inner += BTN + BTN + 4;
    if (g.showCancel) inner += BTN;

    roundRect(ctx, x, y, inner, PILL_H, 4);
    ctx.fillStyle = PILL_BG;
    ctx.fill();
    ctx.strokeStyle = g.line.color;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.font = FONT;
    ctx.textBaseline = "middle";
    ctx.fillStyle = g.line.color;
    ctx.textAlign = "left";
    let tx = x + PAD_X;
    ctx.fillText(g.label, tx, y + PILL_H / 2);
    tx += labelW + PAD_X;

    if (g.pnlText) {
      ctx.fillStyle = "rgba(255,255,255,0.12)";
      ctx.fillRect(tx - PAD_X + 2, y + 3, 1, PILL_H - 6);
      ctx.fillStyle = g.pnlColor;
      ctx.fillText(g.pnlText, tx, y + PILL_H / 2);
      tx += measure(g.pnlText, FONT) + PAD_X;
    }

    if (g.showActions) {
      drawReverseIcon(ctx, tx + BTN / 2, y + PILL_H / 2);
      tx += BTN;
      drawCloseIcon(ctx, tx + BTN / 2, y + PILL_H / 2);
      tx += BTN;
    } else if (g.showCancel) {
      drawCloseIcon(ctx, tx + BTN / 2, y + PILL_H / 2);
      tx += BTN;
    }
  }
}

class PaneView implements IPrimitivePaneView {
  private _source: TradingLinesPrimitive;
  private _geoms: LineGeom[] = [];

  constructor(source: TradingLinesPrimitive) {
    this._source = source;
  }

  zOrder() {
    return "top" as const;
  }

  update() {
    const series = this._source.series();
    const lines = this._source.lines();
    const hits: HitBox[] = [];
    const geoms: LineGeom[] = [];
    if (!series) {
      this._geoms = [];
      this._source.setHits([]);
      return;
    }
    const paneW = this._source.paneWidth();
    for (const line of lines) {
      const y = series.priceToCoordinate(line.price);
      if (y == null) continue;
      const geom = layoutLine(line, y, paneW);
      geoms.push(geom);
      hits.push(...geom.hits);
    }
    this._geoms = geoms;
    this._source.setHits(hits);
  }

  renderer() {
    return new PaneRenderer(this._geoms);
  }
}

function pillWidth(line: ChartOverlay, pnlText: string | null, showActions: boolean, showCancel: boolean): number {
  const labelW = measure(line.label, FONT);
  let inner = PAD_X + labelW + PAD_X;
  if (pnlText) inner += 2 + measure(pnlText, FONT) + PAD_X;
  if (showActions) inner += BTN + BTN + 4;
  if (showCancel) inner += BTN;
  return inner;
}

function layoutLine(line: ChartOverlay, y: number, paneW: number): LineGeom {
  const pillY = y - PILL_H / 2;
  const interactive = Boolean(line.interactive);
  const showActions = line.kind === "position" && interactive;
  const showCancel = (line.kind === "order" || line.kind === "algo") && interactive;
  const pnlText =
    line.kind === "position" && line.pnl != null && Number.isFinite(line.pnl)
      ? formatUsd(line.pnl)
      : null;
  const pnlColor =
    (line.pnl ?? 0) > 0 ? theme.bid : (line.pnl ?? 0) < 0 ? theme.ask : theme.muted;

  const width = pillWidth(line, pnlText, showActions, showCancel);
  // Orders/algos stay left; position sits near mid-pane to avoid overlap.
  const pillX =
    line.kind === "position" && paneW > 0
      ? Math.max(LEFT, Math.round(paneW * POSITION_X_FRAC - width / 2))
      : LEFT;

  const hits: HitBox[] = [];
  if (line.kind !== "band") {
    let tx = pillX + PAD_X + measure(line.label, FONT) + PAD_X;
    if (pnlText) tx += measure(pnlText, FONT) + PAD_X;
    if (showActions) {
      hits.push({ x: tx, y: pillY, w: BTN, h: PILL_H, id: line.id, action: "reverse" });
      tx += BTN;
      hits.push({ x: tx, y: pillY, w: BTN, h: PILL_H, id: line.id, action: "close" });
    } else if (showCancel) {
      hits.push({ x: tx, y: pillY, w: BTN, h: PILL_H, id: line.id, action: "cancel" });
    }
  }

  return {
    line,
    y,
    hits,
    pillX,
    pillY,
    label: line.label,
    pnlText,
    pnlColor,
    showActions,
    showCancel,
  };
}

export class TradingLinesPrimitive implements ISeriesPrimitive {
  private _series: ISeriesApi<SeriesType> | undefined;
  private _chart: IChartApiBase<unknown> | undefined;
  private _requestUpdate: (() => void) | undefined;
  private _lines: ChartOverlay[] = [];
  private _hits: HitBox[] = [];
  private readonly _paneView = new PaneView(this);
  private _paneViews: PaneView[] = [this._paneView];
  private _priceAxisViews: PriceAxisLabel[] = [];
  private _axisKey = "";

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

  lines() {
    return this._lines;
  }

  lineById(id: string) {
    return this._lines.find((l) => l.id === id);
  }

  setHits(hits: HitBox[]) {
    this._hits = hits;
  }

  setLines(lines: ChartOverlay[]) {
    this._lines = lines;
    const key = lines.map((l) => l.id).join("\0");
    if (key !== this._axisKey) {
      this._axisKey = key;
      this._priceAxisViews = lines.map((l) => new PriceAxisLabel(this, l.id));
      this._paneViews = [this._paneView];
    }
    this._requestUpdate?.();
  }

  updateAllViews() {
    this._paneView.update();
    for (const v of this._priceAxisViews) v.update();
  }

  paneViews() {
    return this._paneViews;
  }

  priceAxisViews() {
    return this._priceAxisViews;
  }

  hitTest(x: number, y: number) {
    for (const box of this._hits) {
      if (x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h) {
        return {
          externalId: `${box.id}::${box.action}`,
          zOrder: "top" as const,
          cursorStyle: "pointer",
        };
      }
    }
    return null;
  }
}

export function parseOverlayAction(raw: unknown): OverlayAction | null {
  if (typeof raw !== "string") return null;
  const sep = raw.indexOf("::");
  if (sep < 0) return null;
  const id = raw.slice(0, sep);
  const action = raw.slice(sep + 2);
  if (
    action !== "close" &&
    action !== "reverse" &&
    action !== "cancel"
  ) {
    return null;
  }
  return { id, action };
}
