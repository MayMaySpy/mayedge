import { useEffect, useState } from "react";
import { api, type PortfolioNow } from "@/lib/api";
import { utcMidnightMs } from "@/lib/portfolioDay";

const POLL_MS = 60_000;
/** Older than this, the header shows nothing rather than a stale figure. */
const STALE_MS = 5 * 60_000;

/** Today's Portfolio totals for the header: the plain answer, once a minute while the tab is visible (N8, N9). */
export function usePortfolioToday(enabled: boolean): PortfolioNow | null {
  const [last, setLast] = useState<{ at: number; data: PortfolioNow } | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const load = () => {
      if (document.visibilityState === "hidden") return;
      api
        .portfolio(utcMidnightMs(), false)
        .then((data) => {
          if (live) setLast({ at: Date.now(), data });
        })
        .catch(() => {
          /* Keep the last figure until it goes stale. */
        })
        .finally(() => {
          if (live) setNow(Date.now());
        });
    };
    load();
    const id = window.setInterval(load, POLL_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      live = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", load);
    };
  }, [enabled]);

  if (!enabled || last == null || now - last.at > STALE_MS) return null;
  return last.data;
}
