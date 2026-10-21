import { DESK_DATE_LOCALE } from "@/lib/utcTime";

/** Theme tokens for JS APIs (charts, canvas) that can't use Tailwind classes. */
export const theme = {
  canvas: "#0b1018",
  panel: "#141c26",
  elevated: "#1a232e",
  rule: "#2c3542",
  muted: "#8b97a8",
  bid: "#3dcc7a",
  ask: "#ee5a68",
  warn: "#e0b04a",
  text: "#e8eef6",
  fontSans: '"IBM Plex Sans", system-ui, sans-serif',
  fontMono: '"IBM Plex Mono", ui-monospace, monospace',
  /** Matches `--text-sm` (chart axis / overlay pills). */
  chartFontSize: 11,
  /** Chart time axes read "21 Oct", not the browser's month names. */
  chartLocale: DESK_DATE_LOCALE,
} as const;
