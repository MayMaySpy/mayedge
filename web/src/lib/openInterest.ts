import type { LineData, UTCTimestamp, WhitespaceData } from "lightweight-charts";
import type { OpenInterestSample } from "@/lib/api";

export type { OpenInterestSample };

export type OiLinePoint = LineData<UTCTimestamp> | WhitespaceData<UTCTimestamp>;

const EMPTY_LINE: OiLinePoint[] = [];

/** Unix seconds of the chart bucket that contains `nowSec`. */
export function bucketOpen(nowSec: number, stepSec: number): number {
  if (stepSec <= 0) return nowSec;
  return Math.floor(nowSec / stepSec) * stepSec;
}

/**
 * Line points for the chart. A gap wider than one bucket becomes a break
 * (whitespace), so a missing sample is not drawn as a straight line.
 * `live` updates the open bucket; it does not fill earlier gaps.
 */
export function buildOiLine(
  samples: readonly OpenInterestSample[],
  stepSec: number,
  live: { time: number; value: number } | null,
): OiLinePoint[] {
  const points: { time: number; value: number }[] = [];
  const sorted = [...samples].sort((a, b) => a.time - b.time);
  for (const sample of sorted) {
    const time = Math.floor(sample.time);
    const value = sample.open_interest;
    if (!Number.isFinite(time) || time <= 0) continue;
    if (!Number.isFinite(value) || value <= 0) continue;
    const last = points[points.length - 1];
    if (last && last.time === time) last.value = value;
    else if (!last || time > last.time) points.push({ time, value });
  }
  if (
    live &&
    Number.isFinite(live.time) &&
    live.time > 0 &&
    Number.isFinite(live.value) &&
    live.value > 0
  ) {
    const last = points[points.length - 1];
    if (!last || live.time > last.time) points.push({ time: live.time, value: live.value });
    else if (live.time === last.time) last.value = live.value;
  }
  if (points.length === 0) return EMPTY_LINE;
  const out: OiLinePoint[] = [];
  let prev: number | null = null;
  for (const point of points) {
    if (prev != null && stepSec > 0 && point.time - prev > stepSec) {
      const gap = prev + stepSec;
      if (gap < point.time) out.push({ time: gap as UTCTimestamp });
    }
    out.push({ time: point.time as UTCTimestamp, value: point.value });
    prev = point.time;
  }
  return out;
}
