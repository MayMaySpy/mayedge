/** Desk clock times, in UTC: the desk never uses local time. Headers or tooltips say UTC once. */

const UTC = { timeZone: "UTC", hourCycle: "h23" } as const;

/** Dates read "20 Oct" in every browser, beside the desk's one number format. */
export const DESK_DATE_LOCALE = "en-GB";

const clockFmt = new Intl.DateTimeFormat(DESK_DATE_LOCALE, { ...UTC, hour: "2-digit", minute: "2-digit", second: "2-digit" });
const minuteFmt = new Intl.DateTimeFormat(DESK_DATE_LOCALE, { ...UTC, hour: "2-digit", minute: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat(DESK_DATE_LOCALE, {
  ...UTC,
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** Seconds or ms: a value above 1e12 is ms. */
function toMs(ts: number): number {
  return ts > 1e12 ? ts : ts * 1000;
}

/** "16:49:57", or "16:49" without seconds. */
export function utcClock(ts: number | null | undefined, seconds = true): string {
  if (!ts) return "—";
  return (seconds ? clockFmt : minuteFmt).format(toMs(ts));
}

/** "20 Oct, 16:49". */
export function utcDateTime(ts: number | null | undefined): string {
  if (!ts) return "—";
  return dateTimeFmt.format(toMs(ts));
}
