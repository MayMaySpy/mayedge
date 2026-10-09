import type { AlertBoardRow, AlertEvent, AlertFactorRow, AlertKind } from "@/lib/api";
import { formatUsdCompact } from "@/lib/utils";
import { pairLabel } from "@/lib/venuePair";

const SETUP: Record<string, { short: string; long: string }> = {
  breakout_longs: { short: "Breakout", long: "Breakout: longs opening" },
  short_squeeze: { short: "Short squeeze", long: "Short squeeze: shorts covering" },
  breakdown_shorts: { short: "Breakdown", long: "Breakdown: shorts opening" },
  long_flush: { short: "Long flush", long: "Long flush: longs exiting" },
  pump: { short: "Sharp up", long: "Sharp move up" },
  dump: { short: "Sharp down", long: "Sharp move down" },
  broad_up: { short: "Broad up", long: "Broad move up" },
  broad_down: { short: "Broad down", long: "Broad move down" },
  holds_up: { short: "Holds up", long: "Holds up: stronger than the market" },
  lags: { short: "Lags", long: "Lags: weaker than the market" },
  vol_surge: { short: "Vol surge", long: "Volume surge" },
  absorption: { short: "Absorption", long: "Absorption: heavy volume, price flat" },
  crowded_longs: { short: "Crowded longs", long: "Crowded longs: premium or funding stretched" },
  crowded_shorts: { short: "Crowded shorts", long: "Crowded shorts: premium or funding stretched" },
  mark_off_book: { short: "Off mark", long: "Mark off book: mid far from mark" },
  liq_cascade: { short: "Liq cascade", long: "Liquidation cascade" },
  mixed: { short: "Unusual", long: "Unusual activity" },
};

const LEGACY_KIND: Record<AlertKind, string> = {
  oi: "OI",
  volume: "Vol",
  price: "Price",
  premium: "Premium",
  dislocation: "Off mark",
  funding: "Funding",
  liq_cluster: "Liqs",
  tone: "Tone",
  signal: "Signal",
};

export function setupShort(key: string | undefined): string {
  return (key && SETUP[key]?.short) || "Signal";
}

export function setupLong(key: string | undefined): string {
  return (key && SETUP[key]?.long) || "Signal";
}

function signed(v: number, digits: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

export function factorText(f: AlertFactorRow): string {
  const v = f.value;
  switch (f.kind) {
    case "price": {
      const px = `Px ${signed(v, 2)}%`;
      return f.excess == null ? px : `${px} · ex ${signed(f.excess, 2)}%`;
    }
    case "broad": {
      const side = f.direction === "up" || f.direction === "down" ? f.direction : "";
      const tail = [f.window, side].filter(Boolean).join(" ");
      const board = `Board ${signed(v, 1)}%`;
      return tail ? `${board} · ${tail}` : board;
    }
    case "volume":
      return `Vol ${v.toFixed(1)}×`;
    case "oi":
      return `OI ${signed(v, 1)}%`;
    case "premium":
      return `Prem ${signed(v, 2)}%`;
    case "dislocation":
      return `Off mark ${v.toFixed(0)}bp`;
    case "funding":
      return `Fund ${signed(v, 4)}%/h`;
    case "liq_cluster":
      return `Liqs ${formatUsdCompact(v) || "$0"}`;
    default:
      return f.kind;
  }
}

export function factorSummary(factors: readonly AlertFactorRow[] | undefined, max = 3): string {
  return (factors ?? []).slice(0, max).map(factorText).join(" · ");
}

function factorDetail(f: AlertFactorRow): string {
  const win = f.window ? ` (${f.window})` : "";
  const sigma = f.score != null ? ` · ${f.score.toFixed(1)}σ` : "";
  return `${factorText(f)}${win}${sigma}`;
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
  if (sev >= 3) return "border-ask";
  if (sev >= 2) return "border-warn";
  return "border-transparent";
}

export function severityText(sev: number): string {
  if (sev >= 3) return "text-ask";
  if (sev >= 2) return "text-warn";
  return "text-muted-foreground";
}

export function eventMs(ts: number | undefined): number {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

export function alertStartMs(ev: AlertEvent): number {
  return eventMs(ev.started_at ?? ev.ts);
}

export function formatClock(ms: number): string {
  if (!ms) return "—";
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function alertName(symbol: string, marketIndex?: number): string {
  if (marketIndex === -1) return "Market";
  return pairLabel(symbol);
}

export type AlertLine = {
  key: string;
  symbol: string;
  name: string;
  /** Broad move uses BTC only so a click opens that chart. Muting it would hide BTC. */
  mutable: boolean;
  direction: string;
  severity: number;
  label: string;
  detail: string;
  score: number | null;
  atMs: number | null;
  tooltip: string;
};

export function eventLine(ev: AlertEvent): AlertLine {
  const atMs = alertStartMs(ev);
  const name = alertName(ev.symbol, ev.market_index);
  if (ev.kind === "signal") {
    const factors = ev.factors ?? [];
    return {
      key: ev.id,
      symbol: ev.symbol,
      name,
      mutable: ev.market_index !== -1,
      direction: ev.direction,
      severity: ev.severity,
      label: setupShort(ev.setup),
      detail: factorSummary(factors),
      score: ev.score ?? null,
      atMs,
      tooltip: [
        `${name} · ${setupLong(ev.setup)}`,
        ...factors.map(factorDetail),
        `Started ${new Date(atMs).toLocaleTimeString()}`,
      ].join("\n"),
    };
  }
  const label = ev.kind === "tone" ? ev.note : (LEGACY_KIND[ev.kind] ?? ev.kind);
  return {
    key: ev.id,
    symbol: ev.symbol,
    name,
    mutable: ev.market_index !== -1,
    direction: ev.direction,
    severity: ev.severity,
    label,
    detail: ev.kind === "tone" ? "" : ev.note,
    score: null,
    atMs,
    tooltip: `${ev.symbol} · ${ev.note}`,
  };
}

export function boardLine(row: AlertBoardRow): AlertLine {
  const parts = [factorSummary(row.factors)];
  const priced = row.factors.some((f) => f.kind === "price" || f.kind === "broad");
  if (row.move_pct != null && !priced) {
    parts.push(`5m ${signed(row.move_pct, 2)}%`);
  }
  const name = alertName(row.symbol, row.market_index);
  return {
    key: `live-${row.market_index}`,
    symbol: row.symbol,
    name,
    mutable: row.market_index !== -1,
    direction: row.direction,
    severity: row.severity ?? 1,
    label: setupShort(row.setup),
    detail: parts.filter(Boolean).join(" · "),
    score: row.score,
    atMs: null,
    tooltip: [`${name} · ${setupLong(row.setup)}`, ...row.factors.map(factorDetail)].join("\n"),
  };
}

/** Newest episode of a market already shown under Live would repeat it; older history stays. */
export function recentEvents(
  events: readonly AlertEvent[],
  liveMarkets: ReadonlySet<number>,
  nowMs: number,
  dedupeWindowMs = 10 * 60_000
): AlertEvent[] {
  const sorted = [...events].sort((a, b) => alertStartMs(b) - alertStartMs(a));
  const hidden = new Set<number>();
  return sorted.filter((ev) => {
    if (ev.kind !== "signal" || !liveMarkets.has(ev.market_index) || hidden.has(ev.market_index)) {
      return true;
    }
    if (nowMs - eventMs(ev.ts) > dedupeWindowMs) return true;
    hidden.add(ev.market_index);
    return false;
  });
}

export function toastCopy(ev: AlertEvent, pair: string): { title: string; description: string } {
  const arrow = directionArrow(ev.direction);
  const head = `${arrow ? `${arrow} ` : ""}${pair}`;
  if (ev.kind !== "signal") return { title: head, description: eventLine(ev).label };
  return { title: `${head} · ${setupShort(ev.setup)}`, description: factorSummary(ev.factors) };
}
