/** Bar size of the price chart, and which of those sizes stay on the chip row. */

export const PIN_CAP = 7;
export const DEFAULT_TIMEFRAME = "1m";
export const DEFAULT_PINS = ["1s", "1m", "5m", "15m", "1h", "4h", "1d"] as const;

const TF_KEY = "mayedge-chart-tf";
const PINS_KEY = "mayedge-chart-tf-pins";

const MAX_SECONDS = 30 * 86_400;
const CANDLE_COUNT = 500;
const ONE_SECOND_SPAN = 3600;

const UNIT_SECONDS = { s: 1, m: 60, h: 3600, d: 86_400 } as const;

export interface Timeframe {
  label: string;
  seconds: number;
}

/** Lighter candle resolutions, plus the desk's own 1s buffer. */
export type CandleSource = "1s" | "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "12h" | "1d";

const NATIVES: { source: Exclude<CandleSource, "1s">; seconds: number }[] = [
  { source: "1d", seconds: 86_400 },
  { source: "12h", seconds: 43_200 },
  { source: "4h", seconds: 14_400 },
  { source: "1h", seconds: 3600 },
  { source: "30m", seconds: 1800 },
  { source: "15m", seconds: 900 },
  { source: "5m", seconds: 300 },
  { source: "1m", seconds: 60 },
];

const OI_LABELS = new Set(["1m", "5m", "15m", "1h", "4h", "1d"]);

/** Menu rows before pins and the active size are merged in. */
const CATALOG = [
  "1s",
  "5s",
  "15s",
  "30s",
  "1m",
  "3m",
  "5m",
  "10m",
  "15m",
  "30m",
  "1h",
  "2h",
  "4h",
  "6h",
  "12h",
  "1d",
];

const UNITS = ["Seconds", "Minutes", "Hours", "Days"] as const;
export type TimeframeUnit = (typeof UNITS)[number];

export interface TimeframeRow {
  label: string;
  depth: string | null;
  pinned: boolean;
}

export interface TimeframeGroup {
  unit: TimeframeUnit;
  rows: TimeframeRow[];
}

export function parseTimeframe(raw: string): Timeframe | null {
  const match = raw.trim().toLowerCase().match(/^(\d+)([smhd])$/);
  if (!match) return null;
  const count = Number(match[1]);
  if (!Number.isInteger(count) || count < 1) return null;
  const unit = match[2] as keyof typeof UNIT_SECONDS;
  const seconds = count * UNIT_SECONDS[unit];
  if (seconds > MAX_SECONDS) return null;
  return { seconds, label: formatSeconds(seconds) };
}

export function candleSource(tf: Timeframe): CandleSource {
  if (tf.seconds < 60) return "1s";
  for (const native of NATIVES) {
    if (tf.seconds % native.seconds === 0) return native.source;
  }
  return "1s";
}

export function historyDepth(tf: Timeframe): string | null {
  const source = candleSource(tf);
  const sourceSeconds = sourceSecondsOf(source);
  if (sourceSeconds === tf.seconds) return null;
  const span = source === "1s" ? ONE_SECOND_SPAN : CANDLE_COUNT * sourceSeconds;
  return formatSpan(span);
}

export function supportsOpenInterest(tf: Timeframe): boolean {
  return OI_LABELS.has(tf.label);
}

export function showsSeconds(tf: Timeframe): boolean {
  return tf.seconds % 60 !== 0;
}

export function togglePin(
  pins: readonly string[],
  label: string
): { pins: string[]; full: boolean } {
  const tf = parseTimeframe(label);
  if (!tf) return { pins: [...pins], full: false };
  if (pins.includes(tf.label)) {
    return { pins: pins.filter((pin) => pin !== tf.label), full: false };
  }
  if (pins.length >= PIN_CAP) return { pins: [...pins], full: true };
  return { pins: [...pins, tf.label], full: false };
}

export function readStoredTimeframe(raw: string | null): string {
  if (!raw) return DEFAULT_TIMEFRAME;
  return parseTimeframe(raw)?.label ?? DEFAULT_TIMEFRAME;
}

export function readStoredPins(raw: string | null): string[] {
  if (raw == null) return [...DEFAULT_PINS];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [...DEFAULT_PINS];
  }
  if (!Array.isArray(parsed)) return [...DEFAULT_PINS];
  const pins: string[] = [];
  for (const item of parsed) {
    if (typeof item !== "string") continue;
    const tf = parseTimeframe(item);
    if (!tf || pins.includes(tf.label)) continue;
    pins.push(tf.label);
    if (pins.length === PIN_CAP) break;
  }
  return pins;
}

export function timeframeMenu(pins: readonly string[], active: string): TimeframeGroup[] {
  const labels = new Set<string>();
  for (const label of [...CATALOG, ...pins, active]) {
    const tf = parseTimeframe(label);
    if (tf) labels.add(tf.label);
  }
  const byUnit = new Map<TimeframeUnit, Timeframe[]>();
  for (const label of labels) {
    const tf = parseTimeframe(label)!;
    const unit = unitOf(tf);
    const rows = byUnit.get(unit) ?? [];
    rows.push(tf);
    byUnit.set(unit, rows);
  }
  return UNITS.flatMap((unit) => {
    const rows = byUnit.get(unit);
    if (!rows?.length) return [];
    rows.sort((a, b) => a.seconds - b.seconds);
    return [
      {
        unit,
        rows: rows.map((tf) => ({
          label: tf.label,
          depth: historyDepth(tf),
          pinned: pins.includes(tf.label),
        })),
      },
    ];
  });
}

export function loadTimeframe(): string {
  try {
    return readStoredTimeframe(localStorage.getItem(TF_KEY));
  } catch {
    return DEFAULT_TIMEFRAME;
  }
}

export function persistTimeframe(label: string): void {
  try {
    localStorage.setItem(TF_KEY, label);
  } catch {
    /* ignore */
  }
}

export function loadPins(): string[] {
  try {
    return readStoredPins(localStorage.getItem(PINS_KEY));
  } catch {
    return [...DEFAULT_PINS];
  }
}

export function persistPins(pins: readonly string[]): void {
  try {
    localStorage.setItem(PINS_KEY, JSON.stringify(pins));
  } catch {
    /* ignore */
  }
}

function formatSeconds(seconds: number): string {
  if (seconds % UNIT_SECONDS.d === 0) return `${seconds / UNIT_SECONDS.d}d`;
  if (seconds % UNIT_SECONDS.h === 0) return `${seconds / UNIT_SECONDS.h}h`;
  if (seconds % UNIT_SECONDS.m === 0) return `${seconds / UNIT_SECONDS.m}m`;
  return `${seconds}s`;
}

function sourceSecondsOf(source: CandleSource): number {
  if (source === "1s") return 1;
  return NATIVES.find((native) => native.source === source)?.seconds ?? 60;
}

function formatSpan(span: number): string {
  if (span < 48 * 3600) {
    const hours = Math.max(1, Math.round(span / 3600));
    return `~${hours}h`;
  }
  const days = Math.max(1, Math.round(span / 86_400));
  return `~${days}d`;
}

function unitOf(tf: Timeframe): TimeframeUnit {
  if (tf.label.endsWith("d")) return "Days";
  if (tf.label.endsWith("h")) return "Hours";
  if (tf.label.endsWith("m")) return "Minutes";
  return "Seconds";
}
