import { useEffect, useRef, useState } from "react";
import { preferPerpMarket, sameMarketIndex } from "@/lib/algos";
import { api, type AccountTrade, type Candle, type Market } from "@/lib/api";
import { armFillToasts, consumeLiveFills } from "@/lib/fillNotice";
import { notifyOrder } from "@/lib/notify";
import {
  applyBookDelta,
  applyBookSnapshot,
  applyMarketQuotes,
  clearBook,
  clearMinuteCandles,
  clearTrades,
  prependAccountTrades,
  prependAlerts,
  prependLiquidations,
  prependTrades,
  resetLiveSession,
  seedAlerts,
  seedLiquidations,
  setAccount,
  setAlgo,
  setBookSynced,
  setFeedHealth,
  setMinuteCandles,
  upsertMinuteCandle,
  type MarketQuote,
} from "@/lib/liveData";

export type { OrderBookLevel, Trade } from "@/lib/liveData";

export interface MarketDataState {
  connected: boolean;
  network: string;
  trading_enabled: boolean;
  markets: Market[];
}

const WS_URL =
  (location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host + "/ws";

const RECONNECT_MS = 3000;

function closeSocket(ws: WebSocket) {
  ws.onopen = null;
  ws.onmessage = null;
  ws.onerror = null;
  ws.onclose = null;
  if (ws.readyState === WebSocket.CONNECTING) {
    ws.addEventListener("open", () => ws.close());
    return;
  }
  if (ws.readyState === WebSocket.OPEN) ws.close();
}

export function useMarketWs(symbol: string) {
  const [state, setState] = useState<MarketDataState>({
    connected: false,
    network: "testnet",
    trading_enabled: false,
    markets: [],
  });
  const wsRef = useRef<WebSocket | null>(null);
  const symbolRef = useRef(symbol);
  const marketsRef = useRef(state.markets);
  const marketIndexRef = useRef<number | null>(null);
  const resyncAtRef = useRef(0);

  useEffect(() => {
    marketsRef.current = state.markets;
  }, [state.markets]);

  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);

  useEffect(() => {
    const m = preferPerpMarket(state.markets, symbol);
    const idx = m?.market_index ?? null;
    const prev = marketIndexRef.current;
    marketIndexRef.current = idx;
    if (
      idx != null &&
      !sameMarketIndex(idx, prev) &&
      wsRef.current?.readyState === WebSocket.OPEN
    ) {
      wsRef.current.send(
        JSON.stringify({
          type: "subscribe_market",
          symbol: symbolRef.current,
          market_index: idx,
        })
      );
    }
  }, [symbol, state.markets]);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleReconnect = () => {
      if (cancelled) return;
      reconnectTimer = setTimeout(connect, RECONNECT_MS);
    };

    const requestBookResync = (ws: WebSocket) => {
      const now = performance.now();
      if (now - resyncAtRef.current < 2000) return;
      resyncAtRef.current = now;
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resync_book" }));
      }
    };

    const isActiveMarket = (msg: { market_index?: number | string | null }) => {
      const want = marketIndexRef.current;
      if (msg.market_index == null || msg.market_index === "") return false;
      if (want == null) return true;
      return sameMarketIndex(msg.market_index, want);
    };

    const subscribe = (ws: WebSocket) => {
      const m = preferPerpMarket(marketsRef.current, symbolRef.current);
      const idx = m?.market_index ?? null;
      marketIndexRef.current = idx;
      const payload: Record<string, unknown> = {
        type: "subscribe_market",
        symbol: symbolRef.current,
      };
      if (idx != null) payload.market_index = idx;
      ws.send(JSON.stringify(payload));
    };

    const connect = () => {
      if (cancelled) return;
      const current = wsRef.current;
      if (
        current &&
        (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) {
          ws.close();
          return;
        }
        setState((s) => ({ ...s, connected: true }));
        armFillToasts();
        subscribe(ws);
        api.account().then((a) => setAccount(a)).catch(() => {});
        api
          .liquidations({ limit: 200 })
          .then(seedLiquidations)
          .catch(() => {});
        api
          .alerts({ limit: 200 })
          .then(seedAlerts)
          .catch(() => {});
      };

      ws.onmessage = (ev) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(ev.data) as Record<string, unknown>;
        } catch {
          return;
        }
        try {
        switch (msg.type) {
          case "init": {
            const markets = (msg.markets ?? []) as Market[];
            const m = preferPerpMarket(markets, symbolRef.current);
            if (m) marketIndexRef.current = m.market_index;
            setState((s) => ({
              ...s,
              network: String(msg.network ?? s.network),
              trading_enabled: Boolean(msg.trading_enabled ?? s.trading_enabled),
              markets: (msg.markets as Market[]) ?? s.markets,
            }));
            applyMarketQuotes((msg.markets as Market[]) ?? []);
            break;
          }
          case "market_switch":
            if (
              marketIndexRef.current != null &&
              msg.market_index != null &&
              !sameMarketIndex(msg.market_index, marketIndexRef.current)
            ) {
              clearBook();
              clearTrades();
              clearMinuteCandles();
            }
            break;
          case "order_book":
          case "order_book_snapshot":
            if (!isActiveMarket(msg)) break;
            applyBookSnapshot(
              { bids: (msg.bids as []) ?? [], asks: (msg.asks as []) ?? [] },
              msg.seq as number | undefined
            );
            break;
          case "order_book_delta": {
            if (!isActiveMarket(msg)) break;
            const ok = applyBookDelta(
              { bids: (msg.bids as []) ?? [], asks: (msg.asks as []) ?? [] },
              { seq: msg.seq as number | undefined, prevSeq: msg.prev_seq as number | undefined }
            );
            if (!ok) requestBookResync(ws);
            break;
          }
          case "trades":
            if (!isActiveMarket(msg)) break;
            prependTrades((msg.trades as []) ?? []);
            break;
          case "liquidations":
            prependLiquidations((msg.items as import("@/lib/api").LiquidationEvent[]) ?? []);
            break;
          case "alerts":
            prependAlerts((msg.events as import("@/lib/api").AlertEvent[]) ?? []);
            break;
          case "feed_health":
            setFeedHealth(msg);
            break;
          case "market_stats":
            applyMarketQuotes((msg.markets as MarketQuote[]) ?? []);
            break;
          case "candles":
            if (!isActiveMarket(msg)) break;
            setMinuteCandles((msg.candles ?? []) as Candle[]);
            break;
          case "candle": {
            if (!isActiveMarket(msg)) break;
            const rows = (
              Array.isArray(msg.candles) && msg.candles.length
                ? msg.candles
                : msg.candle
                  ? [msg.candle]
                  : []
            ) as Candle[];
            for (const row of rows) upsertMinuteCandle(row);
            break;
          }
          case "book_sync":
            if (!isActiveMarket(msg)) break;
            setBookSynced(Boolean(msg.synced));
            break;
          case "account":
            setAccount({
              collateral: String(msg.collateral ?? "0"),
              available: String(msg.available ?? "0"),
              trade_available:
                msg.trade_available != null ? String(msg.trade_available) : undefined,
              portfolio_margin:
                msg.portfolio_margin != null ? String(msg.portfolio_margin) : undefined,
              unrealized_pnl: String(msg.unrealized_pnl ?? "0"),
              positions: (msg.positions as import("@/lib/api").Position[]) ?? [],
              open_orders: (msg.open_orders as import("@/lib/api").OpenOrder[]) ?? [],
            });
            break;
          case "account_trades": {
            const trades = (msg.trades ?? []) as AccountTrade[];
            prependAccountTrades(trades);
            for (const notice of consumeLiveFills(trades)) notifyOrder(notice);
            break;
          }
          case "algo":
            setAlgo(msg as unknown as import("@/lib/api").AlgoBook);
            break;
        }
        } catch (err) {
          console.error("ws message", msg.type, err);
        }
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (cancelled) return;
        setState((s) => ({ ...s, connected: false }));
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) {
        closeSocket(wsRef.current);
        wsRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    resetLiveSession();
    clearBook();
    clearTrades();
    clearMinuteCandles();
    setBookSynced(false);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const m = preferPerpMarket(marketsRef.current, symbol);
      const idx = m?.market_index ?? null;
      marketIndexRef.current = idx;
      const payload: Record<string, unknown> = { type: "subscribe_market", symbol };
      if (idx != null) payload.market_index = idx;
      wsRef.current.send(JSON.stringify(payload));
    }
    api.account().then((a) => setAccount(a)).catch(() => {});
    api.algoStatus().then((b) => setAlgo(b)).catch(() => {});
    api.activateMarket(symbol).catch(() => {});
  }, [symbol]);

  return state;
}
