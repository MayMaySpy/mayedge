import { theme } from "@/lib/theme";

/** W9: the PnL card, drawn on a canvas so it saves and copies as a PNG. */

export const CARD_WIDTH = 1200;
export const CARD_HEIGHT = 630;

export type PnlCard = {
  /** "Today", "Last 7 days", … */
  period: string;
  /** "2026-10-20 UTC" or "2026-09-21 → 2026-10-20 UTC". */
  dates: string;
  change: number;
  pct: number | null;
  /** Off leaves every dollar amount off the card: only the % and the curve's shape. */
  showUsd: boolean;
  curve: number[];
};

function signed(value: number, digits: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${sign}${abs}`;
}

export function cardUsd(value: number): string {
  const text = signed(value, 2);
  return text.startsWith("+") || text.startsWith("-") ? `${text[0]}$${text.slice(1)}` : `$${text}`;
}

export function cardPct(value: number): string {
  return `${signed(value, 2)}%`;
}

function tone(value: number): string {
  return value > 0 ? theme.bid : value < 0 ? theme.ask : theme.text;
}

export function drawPnlCard(ctx: CanvasRenderingContext2D, card: PnlCard): void {
  const W = CARD_WIDTH;
  const H = CARD_HEIGHT;
  const left = 72;
  const right = W - 72;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = theme.canvas;
  ctx.fillRect(0, 0, W, H);
  ctx.beginPath();
  ctx.roundRect(24, 24, W - 48, H - 48, 20);
  ctx.fillStyle = theme.panel;
  ctx.fill();
  ctx.strokeStyle = theme.rule;
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = theme.muted;
  ctx.font = `500 28px ${theme.fontSans}`;
  ctx.textAlign = "left";
  ctx.fillText("Portfolio PnL", left, 100);
  ctx.textAlign = "right";
  ctx.fillText(card.period, right, 100);

  const color = tone(card.change);
  ctx.textAlign = "left";
  ctx.fillStyle = color;
  const headline = card.pct != null ? cardPct(card.pct) : card.showUsd ? cardUsd(card.change) : "—";
  ctx.font = `500 132px ${theme.fontSans}`;
  ctx.fillText(headline, left - 6, 250);
  if (card.showUsd && card.pct != null) {
    ctx.font = `500 48px ${theme.fontMono}`;
    ctx.fillText(cardUsd(card.change), left, 324);
  }

  drawCurve(ctx, card.curve, { x0: left, x1: right, y0: 372, y1: 516 }, color);

  ctx.fillStyle = theme.muted;
  ctx.font = `400 24px ${theme.fontMono}`;
  ctx.textAlign = "left";
  ctx.fillText(card.dates, left, 572);
  ctx.textAlign = "right";
  ctx.font = `600 24px ${theme.fontSans}`;
  ctx.fillText("mayedge", right, 572);
}

function drawCurve(
  ctx: CanvasRenderingContext2D,
  values: number[],
  box: { x0: number; x1: number; y0: number; y1: number },
  color: string,
): void {
  if (values.length < 2) return;
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;
  const x = (i: number) => box.x0 + ((box.x1 - box.x0) * i) / (values.length - 1);
  const y = (v: number) => box.y1 - ((v - lo) / span) * (box.y1 - box.y0);

  // Zero, so a range that dipped below its start reads as such.
  ctx.save();
  ctx.setLineDash([6, 8]);
  ctx.strokeStyle = theme.rule;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(box.x0, y(0));
  ctx.lineTo(box.x1, y(0));
  ctx.stroke();
  ctx.restore();

  const fill = ctx.createLinearGradient(0, box.y0, 0, box.y1);
  fill.addColorStop(0, `${color}40`);
  fill.addColorStop(1, `${color}00`);
  ctx.beginPath();
  ctx.moveTo(x(0), y(0));
  values.forEach((v, i) => ctx.lineTo(x(i), y(v)));
  ctx.lineTo(x(values.length - 1), y(0));
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();

  ctx.beginPath();
  values.forEach((v, i) => (i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v))));
  ctx.strokeStyle = color;
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.stroke();
}
