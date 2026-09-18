const WATCH_WINDOW_KEY = "mayedge-watch-window";

export const WATCH_WINDOWS = ["15m", "1h", "4h"] as const;
export type WatchWindow = (typeof WATCH_WINDOWS)[number];
export const WATCH_WINDOW_SEC: Record<WatchWindow, number> = {
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
};

export function loadWatchWindow(): WatchWindow {
  try {
    const raw = localStorage.getItem(WATCH_WINDOW_KEY);
    if (raw && (WATCH_WINDOWS as readonly string[]).includes(raw)) return raw as WatchWindow;
  } catch {
    /* ignore */
  }
  return "15m";
}

export function persistWatchWindow(next: WatchWindow) {
  try {
    localStorage.setItem(WATCH_WINDOW_KEY, next);
  } catch {
    /* ignore */
  }
}
