/**
 * The desk's live stores, fed by the websocket and read with useSyncExternalStore.
 * Each family lives in lib/live/; import from here.
 */
import { flushAccountUi } from "@/lib/live/account";
import { flushBoardsUi } from "@/lib/live/boards";
import { flushMarketUi } from "@/lib/live/market";

export * from "@/lib/live/account";
export * from "@/lib/live/boards";
export * from "@/lib/live/market";

function flushLiveUi() {
  flushMarketUi();
  flushAccountUi();
  flushBoardsUi();
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") flushLiveUi();
  });
}
