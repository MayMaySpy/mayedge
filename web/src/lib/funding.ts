import type { HistogramData, UTCTimestamp, WhitespaceData } from "lightweight-charts";
import type { FundingAverage, FundingSample } from "@/lib/api";
import { theme } from "@/lib/theme";

export type { FundingAverage, FundingSample };

export type FundingBar = HistogramData<UTCTimestamp> | WhitespaceData<UTCTimestamp>;

const EMPTY_BARS: FundingBar[] = [];
const HOURS_PER_YEAR = 24 * 365;
/** An estimate is drawn faint so it never reads as a rate that was paid. */
const ESTIMATE_ALPHA = "66";

/** Lighter's 1h funding percent as APR (0.0012 → 10.512), like the header. */
export function fundingApr(hourlyPct: number): number {
  return hourlyPct * HOURS_PER_YEAR;
}

/** Longs paying is the ask colour, shorts paying the bid colour, as in the header. */
export function fundingColor(apr: number, settled: boolean): string {
  const base = apr > 0 ? theme.ask : apr < 0 ? theme.bid : theme.muted;
  return settled ? base : `${base}${ESTIMATE_ALPHA}`;
}

/** Whether a bar from `buildFundingBars` is a settled print. */
export function isSettled(bar: { customValues?: Record<string, unknown> } | undefined): boolean {
  return bar?.customValues?.settled === true;
}

/**
 * Histogram bars in APR. A gap wider than one bucket becomes a break (whitespace).
 * `live` is the venue's estimate for the open bucket; it never replaces a settled bar.
 */
export function buildFundingBars(
  samples: readonly FundingSample[],
  stepSec: number,
  live: { time: number; rate: number } | null,
): FundingBar[] {
  const points: { time: number; rate: number; settled: boolean }[] = [];
  const sorted = [...samples].sort((a, b) => a.time - b.time);
  for (const sample of sorted) {
    const time = Math.floor(sample.time);
    if (!Number.isFinite(time) || time <= 0 || !Number.isFinite(sample.rate)) continue;
    const point = { time, rate: sample.rate, settled: sample.settled === true };
    const last = points[points.length - 1];
    if (last && last.time === time) points[points.length - 1] = point;
    else if (!last || time > last.time) points.push(point);
  }
  if (live && Number.isFinite(live.time) && live.time > 0 && Number.isFinite(live.rate)) {
    const last = points[points.length - 1];
    const point = { time: live.time, rate: live.rate, settled: false };
    if (!last || live.time > last.time) points.push(point);
    else if (live.time === last.time && !last.settled) points[points.length - 1] = point;
  }
  if (points.length === 0) return EMPTY_BARS;
  const out: FundingBar[] = [];
  let prev: number | null = null;
  for (const point of points) {
    if (prev != null && stepSec > 0 && point.time - prev > stepSec) {
      out.push({ time: (prev + stepSec) as UTCTimestamp });
    }
    const apr = fundingApr(point.rate);
    out.push({
      time: point.time as UTCTimestamp,
      value: apr,
      color: fundingColor(apr, point.settled),
      customValues: { settled: point.settled },
    });
    prev = point.time;
  }
  return out;
}

/** A window counts as its full length once it holds this share of its hours. */
const FULL_WINDOW = 0.95;

/** One window's mean in APR, labelled by the hours it really holds. */
export function averageReading(
  window: FundingAverage["windows"][number] | undefined,
): { label: string; apr: number } | null {
  if (!window || window.rate == null || !Number.isFinite(window.rate) || window.hours <= 0) {
    return null;
  }
  const apr = fundingApr(window.rate);
  if (window.hours >= window.days * 24 * FULL_WINDOW) return { label: window.label, apr };
  if (window.hours < 24) return { label: `${window.hours}h`, apr };
  return { label: `${Math.floor(window.hours / 24)}d`, apr };
}

/** The header's average: the longest window the desk has prints for. */
export function headlineAverage(avg: FundingAverage | null): { label: string; apr: number } | null {
  if (!avg) return null;
  return averageReading(avg.windows[avg.windows.length - 1]);
}
