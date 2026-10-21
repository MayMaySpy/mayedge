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
import { formatUsd } from "@/lib/utils";

export type ChartOverlayKind = "position" | "order" | "liq" | "algo" | "band" | "draft";

export interface ChartOverlay {
  id: string;
  kind: ChartOverlayKind;
  price: number;
  color: string;
  label: string;
  prefixLabel?: string;
  qtyLabel?: string;
  qtyEditable?: boolean;
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

const FONT = `${theme.chartFontSize}px ${theme.fontMono}`;
const PILL_H = 20;
const PAD_X = 7;
const BTN = 18;
const LEFT = 8;
const PILL_BG = "rgba(14, 17, 22, 0.92)";
const REV_YELLOW = theme.warn;
const LINE_HIT = 6;

type HitAction = OverlayActionName | "body" | "size";

type HitBox = {
  x: number;
  y: number;
  w: number;
  h: number;
  id: string;
  action: HitAction;
};

type LineGeom = {
  line: ChartOverlay;
  y: number;
  hits: HitBox[];
  pillX: number;
  pillY: number;
  label: string;
  prefixText: string;
  qtyText: string | null;
  pnlText: string | null;
  pnlColor: string;
  showActions: boolean;
  showCancel: boolean;
  hideQty: boolean;
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

function formatSignedPnl(n: number): string {
  return n > 0 ? `+${formatUsd(n)}` : formatUsd(n);
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
  ctx.strokeStyle = REV_YELLOW;
  ctx.lineWidth = 1.35;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const xUp = cx - 3.1;
  const xDn = cx + 3.1;
  ctx.beginPath();
  ctx.moveTo(xUp, cy + 5);
  ctx.lineTo(xUp, cy - 5);
  ctx.moveTo(xUp - 2.6, cy - 2.2);
  ctx.lineTo(xUp, cy - 5);
  ctx.lineTo(xUp + 2.6, cy - 2.2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(xDn, cy - 5);
  ctx.lineTo(xDn, cy + 5);
  ctx.moveTo(xDn - 2.6, cy + 2.2);
  ctx.lineTo(xDn, cy + 5);
  ctx.lineTo(xDn + 2.6, cy + 2.2);
  ctx.stroke();
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
            g.line.kind === "band" ? LineStyle.Dotted : LineStyle.Dashed
          );
        } else {
          ctx.setLineDash(g.line.kind === "band" ? [2 * hr, 4 * hr] : [4 * hr, 4 * hr]);
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
    const x = g.pillX;
    const labelW = g.qtyText
      ? measure(`${g.prefixText} `, FONT) + measure(g.qtyText, FONT)
      : measure(g.label, FONT);
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
    if (g.qtyText) {
      ctx.fillText(`${g.prefixText} `, tx, y + PILL_H / 2);
      tx += measure(`${g.prefixText} `, FONT);
      if (!g.hideQty) ctx.fillText(g.qtyText, tx, y + PILL_H / 2);
      tx += measure(g.qtyText, FONT) + PAD_X;
    } else {
      ctx.fillText(g.label, tx, y + PILL_H / 2);
      tx += labelW + PAD_X;
    }

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
      const geom = layoutLine(line, y, paneW, this._source.omitQtyId() === line.id);
      geoms.push(geom);
      hits.push(...geom.hits);
    }
    this._geoms = geoms;
    this._source.setGeoms(geoms);
    this._source.setHits(hits);
  }

  renderer() {
    return new PaneRenderer(this._geoms);
  }
}

function labelWidth(line: ChartOverlay): number {
  if (line.qtyEditable && line.prefixLabel && line.qtyLabel) {
    return measure(`${line.prefixLabel} `, FONT) + measure(line.qtyLabel, FONT);
  }
  return measure(line.label, FONT);
}

function pillWidth(line: ChartOverlay, pnlText: string | null, showActions: boolean, showCancel: boolean): number {
  let inner = PAD_X + labelWidth(line) + PAD_X;
  if (pnlText) inner += 2 + measure(pnlText, FONT) + PAD_X;
  if (showActions) inner += BTN + BTN + 4;
  if (showCancel) inner += BTN;
  return inner;
}

function layoutLine(line: ChartOverlay, y: number, paneW: number, hideQty: boolean): LineGeom {
  const pos = line.kind === "position";
  const pillY = y - PILL_H / 2;
  const interactive = Boolean(line.interactive);
  const showActions = pos && interactive;
  const showCancel = (line.kind === "order" || line.kind === "algo") && interactive;
  const splitQty = Boolean(line.qtyEditable && line.prefixLabel && line.qtyLabel);
  const prefixText = splitQty ? line.prefixLabel! : line.label;
  const qtyText = splitQty ? line.qtyLabel! : null;
  const pnlText =
    pos && line.pnl != null && Number.isFinite(line.pnl) ? formatSignedPnl(line.pnl) : null;
  const pnlColor =
    (line.pnl ?? 0) > 0 ? theme.bid : (line.pnl ?? 0) < 0 ? theme.ask : theme.muted;

  const width = pillWidth(line, pnlText, showActions, showCancel);
  const pillX =
    pos && paneW > 0 ? Math.max(LEFT, Math.round((paneW - width) / 2)) : LEFT;

  const hits: HitBox[] = [];
  if (line.kind !== "band") {
    const labelW = labelWidth(line);
    let tx = pillX + PAD_X + labelW + PAD_X;
    if (pnlText) tx += measure(pnlText, FONT) + PAD_X;
    if (showActions) {
      hits.push({ x: tx, y: pillY, w: BTN, h: PILL_H, id: line.id, action: "reverse" });
      tx += BTN;
      hits.push({ x: tx, y: pillY, w: BTN, h: PILL_H, id: line.id, action: "close" });
    } else if (showCancel) {
      hits.push({ x: tx, y: pillY, w: BTN, h: PILL_H, id: line.id, action: "cancel" });
    }
    if (interactive && (line.kind === "order" || line.kind === "draft")) {
      if (splitQty) {
        const prefixW = measure(`${prefixText} `, FONT);
        const qtyW = measure(qtyText!, FONT);
        hits.push({
          x: pillX + PAD_X + prefixW,
          y: pillY,
          w: Math.max(1, qtyW),
          h: PILL_H,
          id: line.id,
          action: "size",
        });
        hits.push({
          x: pillX,
          y: pillY,
          w: Math.max(1, PAD_X + prefixW),
          h: PILL_H,
          id: line.id,
          action: "body",
        });
      } else {
        const pillBodyW = width - (showCancel ? BTN : 0);
        hits.push({ x: pillX, y: pillY, w: Math.max(1, pillBodyW), h: PILL_H, id: line.id, action: "body" });
      }
      hits.push({
        x: 0,
        y: y - LINE_HIT,
        w: Math.max(paneW, 1),
        h: LINE_HIT * 2,
        id: line.id,
        action: "body",
      });
    }
  }

  return {
    line,
    y,
    hits,
    pillX,
    pillY,
    label: line.label,
    prefixText,
    qtyText,
    pnlText,
    pnlColor,
    showActions,
    showCancel,
    hideQty,
  };
}

export class TradingLinesPrimitive implements ISeriesPrimitive {
  private _series: ISeriesApi<SeriesType> | undefined;
  private _chart: IChartApiBase<unknown> | undefined;
  private _requestUpdate: (() => void) | undefined;
  private _lines: ChartOverlay[] = [];
  private _hits: HitBox[] = [];
  private _geoms: LineGeom[] = [];
  private _omitQtyId: string | null = null;
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

  setGeoms(geoms: LineGeom[]) {
    this._geoms = geoms;
  }

  omitQtyId() {
    return this._omitQtyId;
  }

  setOmitQty(id: string | null) {
    if (this._omitQtyId === id) return;
    this._omitQtyId = id;
    this._requestUpdate?.();
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
        const cursorStyle =
          box.action === "body"
            ? ("ns-resize" as const)
            : box.action === "size"
              ? ("text" as const)
              : ("pointer" as const);
        return {
          externalId: `${box.id}::${box.action}`,
          zOrder: "top" as const,
          cursorStyle,
        };
      }
    }
    return null;
  }

  hitAt(x: number, y: number): { overlay: ChartOverlay; region: "cancel" | "body" | "size" } | null {
    for (const prefer of ["size", "cancel", "body"] as const) {
      for (const box of this._hits) {
        if (box.action !== prefer) continue;
        if (x < box.x || x > box.x + box.w || y < box.y || y > box.y + box.h) continue;
        const overlay = this.lineById(box.id);
        if (!overlay) continue;
        return { overlay, region: box.action };
      }
    }
    return null;
  }

  qtyHitRect(id: string): { x: number; y: number; w: number; h: number } | null {
    for (const geom of this._geoms) {
      if (geom.line.id !== id || !geom.qtyText) continue;
      for (const box of geom.hits) {
        if (box.action !== "size") continue;
        return { x: box.x, y: box.y, w: box.w, h: box.h };
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
