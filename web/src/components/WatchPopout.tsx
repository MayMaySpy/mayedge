import { useCallback, useEffect, useState } from "react";
import { WatchBoard } from "@/components/widgets/WatchBoard";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Market } from "@/lib/api";
import { applyMarketQuotes } from "@/lib/liveData";
import { postDesk, subscribeDesk } from "@/lib/deskBridge";
import { replaceWatchSamples, snapshotWatchSamples } from "@/lib/watchSamples";
import {
  WATCH_WINDOWS,
  WATCH_WINDOW_SEC,
  loadWatchWindow,
  persistWatchWindow,
  type WatchWindow,
} from "@/lib/watchWindow";

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

  const selectWatchWindow = (next: WatchWindow) => {
    if (next === watchWindow) return;
    setWatchWindow(next);
    persistWatchWindow(next);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex h-8 shrink-0 items-center border-b border-border px-2">
        <span className="font-mono text-[11px] font-medium">Watch</span>
        <div className="flex-1" />
        <ToggleGroup
          type="single"
          size="sm"
          spacing={0}
          value={watchWindow}
          onValueChange={(v) => {
            if (v && (WATCH_WINDOWS as readonly string[]).includes(v)) {
              selectWatchWindow(v as WatchWindow);
            }
          }}
        >
          {WATCH_WINDOWS.map((w) => (
            <ToggleGroupItem
              key={w}
              value={w}
              title="Path window"
              className="h-5 rounded-sm px-1.5 font-mono text-[10px] data-[state=on]:bg-rule"
            >
              {w}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <WatchBoard
          windowSec={WATCH_WINDOW_SEC[watchWindow]}
          markets={markets}
          symbol={symbol}
          onSymbolChange={onSymbolChange}
        />
      </div>
    </div>
  );
}
