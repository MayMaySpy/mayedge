import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";

const WatchBoard = lazy(() =>
  import("@/components/widgets/WatchBoard").then((m) => ({ default: m.WatchBoard })),
);
import { WatchWindowToggle } from "@/components/widgets/chart/WatchWindowToggle";
import type { Market } from "@/lib/api";
import { applyMarketQuotes } from "@/lib/liveData";
import { postDesk, subscribeDesk } from "@/lib/deskBridge";
import { replaceWatchSamples, snapshotWatchSamples } from "@/lib/watchSamples";
import { WATCH_WINDOW_SEC, loadWatchWindow, type WatchWindow } from "@/lib/watchWindow";

function closeWatch() {
  try {
    window.close();
  } catch {
    /* ignore */
  }
}

export function WatchPopout() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [symbol, setSymbol] = useState("");
  const [watchWindow, setWatchWindow] = useState<WatchWindow>(loadWatchWindow);

  useEffect(() => {
    document.title = "Watch";
    postDesk({ type: "watch-hello" });
    let ready = false;
    const timer = window.setTimeout(() => {
      if (!ready) closeWatch();
    }, 2000);

    const unsub = subscribeDesk((msg) => {
      if (msg.type === "desk-closing") {
        closeWatch();
        return;
      }
      if (msg.type === "desk-state") {
        ready = true;
        applyMarketQuotes(msg.quotes);
        replaceWatchSamples(msg.samples);
        setMarkets(msg.markets);
        if (msg.symbol) setSymbol(msg.symbol);
        return;
      }
      if (msg.type === "quotes") applyMarketQuotes(msg.rows);
      if (msg.type === "markets") setMarkets(msg.markets);
      if (msg.type === "symbol") setSymbol(msg.symbol);
    });

    const onUnload = () => postDesk({ type: "watch-closed", samples: snapshotWatchSamples() });
    window.addEventListener("pagehide", onUnload);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.clearTimeout(timer);
      unsub();
      window.removeEventListener("pagehide", onUnload);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, []);

  const onSymbolChange = useCallback((next: string) => {
    setSymbol(next);
    postDesk({ type: "symbol", symbol: next });
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex h-8 shrink-0 items-center border-b border-border px-2">
        <span className="text-base font-medium">Watch</span>
        <div className="flex-1" />
        <WatchWindowToggle value={watchWindow} onChange={setWatchWindow} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <Suspense
          fallback={
            <Empty className="h-full rounded-none border-0">
              <EmptyHeader>
                <EmptyTitle>Add Markets to Watch</EmptyTitle>
                <EmptyDescription>Plot live Paths for up to 8 Markets.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          }
        >
          <WatchBoard
            windowSec={WATCH_WINDOW_SEC[watchWindow]}
            markets={markets}
            symbol={symbol}
            onSymbolChange={onSymbolChange}
          />
        </Suspense>
      </div>
    </div>
  );
}
