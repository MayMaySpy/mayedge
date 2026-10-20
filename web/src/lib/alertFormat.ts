import type { AlertEvent, AlertFact } from "@/lib/api";
import { formatUsdCompact } from "@/lib/utils";
import { utcClock } from "@/lib/utcTime";
import { pairLabel } from "@/lib/venuePair";

const RULE_NAME: Record<string, string> = {
  move: "Price spike",
  volume: "Volume spike",
  oi: "OI spike",
  liqs: "Liquidations",
  board: "Board move",
  near_liq: "Near liquidation",
};

export function ruleName(rule: string): string {
  return RULE_NAME[rule] ?? rule;
}

function signed(v: number, digits: number): string {
  const text = v.toFixed(digits);
  // A move too small to show is flat, not "-0.00".
  if (Number(text) === 0) return (0).toFixed(digits);
  return v > 0 ? `+${text}` : text;
}

function liquidatedSide(f: AlertFact): string {
  return f.direction === "down" ? "longs" : "shorts";
}

/** What a fact says happened. */
export function headlineText(f: AlertFact): string {
  switch (f.kind) {
    case "move":
      return `${signed(f.value, 2)}% ${f.window ?? ""}`.trim();
    case "volume":
      return `Vol ${formatUsdCompact(f.value) || "$0"} ${f.window ?? ""}`.trim();
    case "oi":
      return `OI ${signed(f.value, 2)}% ${f.window ?? ""}`.trim();
    case "day_high":
      return "day high";
    case "day_low":
      return "day low";
    case "funding":
      return `funding ${signed(f.value, 4)}%/h`;
    case "liqs":
      return `Liqs ${formatUsdCompact(f.value) || "$0"} ${liquidatedSide(f)}`;
    case "board":
      return `${signed(f.value, 2)}% 5m`;
    case "near_liq":
      return `${f.value.toFixed(1)}% from liquidation`;
    default:
      return f.kind;
  }
}

function hourMax(f: AlertFact): string {
  return f.multiple == null ? "" : `${f.multiple.toFixed(1)}× hour max`;
}

/** How big the headline is: against the hour for a spike, against the book for the rest. */
export function supportText(f: AlertFact): string[] {
  switch (f.kind) {
    case "move":
      return [hourMax(f), f.excess == null ? "" : `${signed(f.excess, 2)}% past the board`].filter(
        Boolean
      );
    case "volume":
    case "oi":
      return [hourMax(f)].filter(Boolean);
    case "liqs":
      return f.bps == null ? [] : [`${Math.round(f.bps)} bps of OI`];
    case "board": {
      const [same, movers] = (f.window ?? "").split("/");
      const out = same && movers ? [`${same} of ${movers} movers ${f.direction ?? ""}`.trim()] : [];
      if (f.liquid != null) out.push(`${f.liquid} liquid`);
      return out;
    }
    default:
      return [];
  }
}

/** A fact that is not the headline: another rule on the row, or what the tape showed. */
export function sideText(f: AlertFact): string {
  const text = headlineText(f);
  const spike = f.kind === "move" || f.kind === "volume" || f.kind === "oi";
  // A plain 1m move is just the tape. Anything else that reached the hour's biggest says so.
  if (!spike || f.multiple == null || (f.kind === "move" && f.size == null)) return text;
  return `${text} (${f.multiple.toFixed(1)}×)`;
}

/** Which side the operator holds, and whether the row runs with it. */
export function heldText(ev: AlertEvent): string {
  if (!ev.held) return "";
  if (ev.held === "order") return "working order";
  if (ev.direction !== "up" && ev.direction !== "down") return `your ${ev.held}`;
  if (ev.rule === "near_liq" || ev.rule === "board") return `your ${ev.held}`;
  const against = (ev.held === "long") === (ev.direction === "down");
  return `${against ? "against" : "with"} your ${ev.held}`;
}

export function directionArrow(direction: string | undefined): string {
  if (direction === "up") return "▲";
  if (direction === "down") return "▼";
  return "";
}

export function directionClass(direction: string | undefined): string {
  if (direction === "up") return "text-bid";
  if (direction === "down") return "text-ask";
  return "text-foreground";
}

export function severityBorder(sev: number): string {
  return sev >= 3 ? "border-ask" : "border-warn";
}

export function eventMs(ts: number | undefined): number {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

export function alertStartMs(ev: AlertEvent): number {
  return eventMs(ev.started_at ?? ev.ts);
}

/** "16:49", UTC. */
export function formatClock(ms: number): string {
  return utcClock(ms, false);
}

export function alertName(symbol: string, marketIndex?: number): string {
  if (marketIndex === -1) return "Market";
  return pairLabel(symbol);
}

export type AlertLine = {
  key: string;
  symbol: string;
  name: string;
  /** The Market row uses BTC only so a click opens that chart. Muting it would hide BTC. */
  mutable: boolean;
  held: boolean;
  direction: string;
  severity: number;
  label: string;
  detail: string;
  atMs: number;
  tooltip: string;
};

/** A row reads as its facts. No label says what they mean. */
export function eventLine(ev: AlertEvent): AlertLine {
  const facts = ev.facts ?? [];
  const head = facts.find((f) => f.kind === ev.rule) ?? facts[0];
  const rest = facts.filter((f) => f !== head);
  const detail = [...(head ? supportText(head) : []), ...rest.map(sideText), heldText(ev)].filter(
    Boolean
  );
  const name = alertName(ev.symbol, ev.market_index);
  const atMs = alertStartMs(ev);
  return {
    key: ev.id,
    symbol: ev.symbol,
    name,
    mutable: ev.market_index !== -1,
    held: Boolean(ev.held),
    direction: ev.direction,
    severity: ev.severity,
    label: head ? headlineText(head) : ruleName(ev.rule),
    detail: detail.join(" · "),
    atMs,
    tooltip: [
      `${name} · ${ruleName(ev.rule)}`,
      ...detail,
      `Fired ${utcClock(atMs)} UTC`,
    ].join("\n"),
  };
}

export function toastCopy(ev: AlertEvent, pair: string): { title: string; description: string } {
  const line = eventLine(ev);
  const arrow = directionArrow(ev.direction);
  const name = ev.market_index === -1 ? line.name : pair;
  return { title: `${arrow ? `${arrow} ` : ""}${name} · ${line.label}`, description: line.detail };
}

/** P1, P2 in docs/alert-rules.md. The Market row and a Held market survive Favorites only. */
export function shownAlerts(
  events: readonly AlertEvent[],
  opts: { minSeverity: number; favoritesOnly: boolean; favorites: readonly string[]; muted: ReadonlySet<string> }
): AlertEvent[] {
  return events
    .filter((ev) => {
      if (ev.severity < opts.minSeverity) return false;
      if (ev.market_index === -1) return true;
      if (opts.muted.has(ev.symbol)) return false;
      return !opts.favoritesOnly || Boolean(ev.held) || opts.favorites.includes(ev.symbol);
    })
    .sort((a, b) => alertStartMs(b) - alertStartMs(a));
}
