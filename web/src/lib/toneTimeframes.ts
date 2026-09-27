/** Native timeframes a tone alert can follow. At most two. */

export const TONE_TIMEFRAME_CAP = 2;
export const TONE_TIMEFRAME_CHOICES = ["1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d"] as const;
export const DEFAULT_TONE_TIMEFRAMES = ["30m", "4h"] as const;

/** Drop a selected timeframe, or add one while the set is under the cap. */
export function toggleToneTimeframe(current: readonly string[], label: string): readonly string[] {
  if (current.includes(label)) return current.filter((item) => item !== label);
  if (current.length >= TONE_TIMEFRAME_CAP) return current;
  return [...current, label];
}
