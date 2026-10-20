import { useEffect, useState } from "react";
import { api, type PortfolioDay, type PortfolioHistory, type PortfolioNow } from "@/lib/api";
import { localMidnightMs } from "@/lib/portfolioDay";
import { notifyErr } from "@/lib/notify";

export type PortfolioSpan = "today" | "24h";
export type PortfolioRange = "1d" | "7d" | "30d" | "90d" | "all";

const REFRESH_MS = 60_000;

function openFor(span: PortfolioSpan): number {
  return span === "today" ? localMidnightMs() : Date.now() - 86_400_000;
}

/** Everything the /portfolio page shows. REST only (docs/portfolio-rules.md W1). */
export function usePortfolioPage() {
  const [span, setSpan] = useState<PortfolioSpan>("today");
  const [range, setRange] = useState<PortfolioRange>("30d");
  const [now, setNow] = useState<PortfolioNow | null>(null);
  const [history, setHistory] = useState<PortfolioHistory | null>(null);
  const [days, setDays] = useState<PortfolioDay[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    const load = () => {
      if (document.visibilityState === "hidden") return;
      api
        .portfolio(openFor(span))
        .then((data) => {
          if (!live) return;
          setNow(data);
          setFailed(false);
        })
        .catch(() => {
          if (live) setFailed(true);
        });
    };
    load();
    const id = window.setInterval(load, REFRESH_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      live = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", load);
    };
  }, [span]);

  useEffect(() => {
    let live = true;
    // Days start at local midnight; a 1d range shows today's hours, so it takes 7 days of bars.
    const dayRange = range === "1d" ? "7d" : range;
    Promise.all([api.portfolioHistory(range), api.portfolioDays(dayRange, new Date().getTimezoneOffset())])
      .then(([h, d]) => {
        if (!live) return;
        setHistory(h);
        setDays(d.days);
      })
      .catch((e: unknown) => {
        if (live) notifyErr(e instanceof Error ? e.message : "Failed to load the Portfolio history");
      });
    return () => {
      live = false;
    };
  }, [range]);

  return { span, setSpan, range, setRange, now, history, days, failed };
}

export type PortfolioPageState = ReturnType<typeof usePortfolioPage>;
