import type { AlertBoardRow, AlertEvent, AlertFactorRow, AlertKind } from "@/lib/api";
import { formatUsdCompact } from "@/lib/utils";

const SETUP: Record<string, { short: string; long: string }> = {
  breakout_longs: { short: "Breakout", long: "Breakout: longs opening" },
  short_squeeze: { short: "Short squeeze", long: "Short squeeze: shorts covering" },
  breakdown_shorts: { short: "Breakdown", long: "Breakdown: shorts opening" },
  long_flush: { short: "Long flush", long: "Long flush: longs exiting" },
  pump: { short: "Sharp up", long: "Sharp move up" },
  dump: { short: "Sharp down", long: "Sharp move down" },
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
    case "price":
      return `Px ${signed(v, 2)}%`;
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

export type AlertLine = {
  key: string;
  symbol: string;
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
  if (ev.kind === "signal") {
    const factors = ev.factors ?? [];
    return {
      key: ev.id,
      symbol: ev.symbol,
      direction: ev.direction,
      severity: ev.severity,
      label: setupShort(ev.setup),
      detail: factorSummary(factors),
      score: ev.score ?? null,
      atMs,
      tooltip: [
        `${ev.symbol} · ${setupLong(ev.setup)}`,
        ...factors.map(factorDetail),
        `Started ${new Date(atMs).toLocaleTimeString()}`,
      ].join("\n"),
    };
  }
  const label = ev.kind === "tone" ? ev.note : (LEGACY_KIND[ev.kind] ?? ev.kind);
  return {
    key: ev.id,
    symbol: ev.symbol,
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
  if (row.move_pct != null && !row.factors.some((f) => f.kind === "price")) {
    parts.push(`5m ${signed(row.move_pct, 2)}%`);
  }
  return {
    key: `live-${row.market_index}`,
    symbol: row.symbol,
    direction: row.direction,
    severity: row.severity ?? 1,
    label: setupShort(row.setup),
    detail: parts.filter(Boolean).join(" · "),
    score: row.score,
    atMs: null,
    tooltip: [`${row.symbol} · ${setupLong(row.setup)}`, ...row.factors.map(factorDetail)].join(
      "\n"
    ),
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
