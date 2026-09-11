import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import GridLayout, {
  type LayoutItem,
  useContainerWidth,
  verticalCompactor,
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { notifyErr, notifyOk } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { ChartWidget, type ChartOverlay, type OverlayAction } from "@/components/widgets/ChartWidget";
import { Header } from "@/components/widgets/Header";
import { LiqsPanel } from "@/components/widgets/LiqsPanel";
import { AlertsPanel } from "@/components/widgets/AlertsPanel";
import { OrderBookWidget } from "@/components/widgets/OrderBookWidget";
import { OrderTicket } from "@/components/widgets/orderTicket/OrderTicket";
import { PositionsPanel } from "@/components/widgets/PositionsPanel";
import { QuickTradePanel } from "@/components/widgets/QuickTradePanel";
import { TradesTapeWidget } from "@/components/widgets/TradesTapeWidget";
import { useMarketWs } from "@/hooks/useMarketWs";
import { useDeskRoute } from "@/lib/deskRoute";
import {
  setAlgo,
  useLiveAccount,
  useLiveAlgos,
  useLiveBbo,
  useLiveMinuteCandles,
} from "@/lib/liveData";
import { api, isLongPosition, type Market } from "@/lib/api";
import { algoIsLive, algoOrderKind, preferPerpMarket } from "@/lib/algos";
import { theme } from "@/lib/theme";
import { useTradingReady } from "@/hooks/useTradingReady";
import {
  defaultPanelVisibility,
  PANEL_CATALOG,
  PANEL_IDS,
  type PanelId,
} from "@/lib/panels";
import { loadSlipPct } from "@/components/widgets/orderTicket/math";
import { formatSize } from "@/lib/utils";

const LAYOUT_KEY = "mayedge-layout-v12";
const VISIBILITY_KEY = "mayedge-visibility-v8";

const GRID_COLS = 12;
const GRID_ROWS = 24;
const MARGIN = 4;
const PAD = 4;

/** Chart + book/tape + ticket on top, blotter row below. */
const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: "chart", x: 0, y: 0, w: 7, h: 16, minW: 4, minH: 6 },
  { i: "book", x: 7, y: 0, w: 2, h: 10, minW: 2, minH: 4 },
  { i: "tape", x: 7, y: 10, w: 2, h: 6, minW: 2, minH: 3 },
  { i: "ticket", x: 9, y: 0, w: 3, h: 16, minW: 2, minH: 6 },
  { i: "positions", x: 0, y: 16, w: 7, h: 8, minW: 6, minH: 4 },
  { i: "alerts", x: 7, y: 16, w: 2, h: 8, minW: 2, minH: 3 },
  { i: "liqs", x: 9, y: 16, w: 3, h: 8, minW: 2, minH: 3 },
];

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function layoutsEqual(a: LayoutItem[], b: readonly LayoutItem[]) {
  if (a.length !== b.length) return false;
  const map = new Map(b.map((item) => [item.i, item]));
  return a.every((item) => {
    const other = map.get(item.i);
    return (
      !!other &&
      item.x === other.x &&
      item.y === other.y &&
      item.w === other.w &&
      item.h === other.h
    );
  });
}

function geometryOf(item: LayoutItem): LayoutItem {
  return {
    i: item.i,
    x: item.x,
    y: item.y,
    w: item.w,
    h: item.h,
    minW: item.minW,
    minH: item.minH,
  };
}

function WidgetShell({ children }: { children: ReactNode }) {
  return (
    <div className="panel flex h-full min-h-0 w-full flex-col overflow-hidden">{children}</div>
  );
}

/** Owns live subscriptions so Dashboard/grid doesn't re-render on every BBO/account tick. */
function ChartPanel({
  symbol,
  market,
  tradingEnabled,
  connected,
  onOverlayAction,
  onClose,
}: {
  symbol: string;
  market: Market | null;
  tradingEnabled: boolean;
  connected: boolean;
  onOverlayAction: (action: OverlayAction, overlay: ChartOverlay) => void;
  onClose?: () => void;
}) {
  const accountSnap = useLiveAccount();
  const bbo = useLiveBbo();
  const algoBook = useLiveAlgos();
  const minuteCandles = useLiveMinuteCandles();
  const bid = parseFloat(bbo.bid ?? "");
  const ask = parseFloat(bbo.ask ?? "");
  const bookMid = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid > 0 ? bid : ask > 0 ? ask : 0;
  const lastClose = minuteCandles[minuteCandles.length - 1]?.close ?? 0;
  const liveMark = bookMid || lastClose;

  const overlays = useMemo(() => {
    const lines: ChartOverlay[] = [];
    const pos = accountSnap?.positions.find(
      (p) => p.symbol === symbol && parseFloat(p.size) !== 0
    );
    if (pos) {
      const size = parseFloat(pos.size);
      const entry = parseFloat(pos.entry_price);
      const liq = parseFloat(pos.liquidation_price ?? "");
      const long = isLongPosition(pos);
      const mark =
        liveMark ||
        market?.last_trade_price ||
        parseFloat(pos.mark_price) ||
        0;
      const livePnl =
        mark > 0 && entry > 0 && size !== 0
          ? (mark - entry) * size
          : parseFloat(pos.unrealized_pnl);
      if (entry > 0) {
        lines.push({
          id: "pos",
          kind: "position",
          price: entry,
          color: long ? theme.bid : theme.ask,
          label: `${long ? "LONG" : "SHORT"} ${formatSize(Math.abs(size))} ${symbol}`,
          pnl: livePnl,
          marketIndex: pos.market_index,
          size: Math.abs(size),
          side: long ? "buy" : "sell",
          interactive: tradingEnabled,
        });
      }
      if (liq > 0) {
        lines.push({
          id: "liq",
          kind: "liq",
          price: liq,
          color: theme.ask,
          label: "Liq",
        });
      }
    }
    const orders = (accountSnap?.open_orders ?? []).filter((o) => o.symbol === symbol);
    for (const o of orders.slice(0, 24)) {
      const px = parseFloat(o.price);
      if (!(px > 0)) continue;
      const buy = o.side === "buy";
      const kind = algoOrderKind(o.client_order_index);
      const tag = kind ? `${kind} ` : "";
      lines.push({
        id: `ord-${o.order_index}`,
        kind: "order",
        price: px,
        color: buy ? theme.bid : theme.ask,
        label: `${tag}${buy ? "BUY" : "SELL"} ${formatSize(o.remaining)}`,
        marketIndex: o.market_index,
        orderIndex: o.order_index,
        interactive: tradingEnabled && !kind,
      });
    }
    for (const algo of algoBook.working) {
      if (!algoIsLive(algo.status) || algo.symbol !== symbol) continue;
      const id = algo.algo_id ?? "chase";
      const floor = parseFloat(algo.price_floor ?? "");
      const ceil = parseFloat(algo.price_ceiling ?? "");
      if (floor > 0) {
        lines.push({
          id: `${id}-floor`,
          kind: "band",
          price: floor,
          color: `${theme.muted}cc`,
          label: `${id} FLOOR`,
        });
      }
      if (ceil > 0) {
        lines.push({
          id: `${id}-ceil`,
          kind: "band",
          price: ceil,
          color: `${theme.muted}cc`,
          label: `${id} CEIL`,
        });
      }
    }
    return lines;
  }, [accountSnap, algoBook.working, symbol, tradingEnabled, liveMark, market]);

  return (
    <ChartWidget
      symbol={symbol}
      priceDecimals={market?.price_decimals ?? 2}
      overlays={overlays}
      onOverlayAction={onOverlayAction}
      onClose={onClose}
    >
      <QuickTradePanel market={market} tradingEnabled={tradingEnabled} connected={connected} />
    </ChartWidget>
  );
}

export function Dashboard() {
  const { symbol, setSymbol, setPair } = useDeskRoute();
  const [layout, setLayout] = useState<LayoutItem[]>(() => {
    const known = new Set<string>(PANEL_IDS);
    const raw = loadJson(LAYOUT_KEY, DEFAULT_LAYOUT);
    const next = raw.filter((item) => known.has(item.i));
    return next.length ? next : DEFAULT_LAYOUT;
  });
  const [visible, setVisible] = useState<Record<string, boolean>>(() =>
    loadJson(VISIBILITY_KEY, defaultPanelVisibility())
  );
  const [editing, setEditing] = useState(false);
  const [tradingEnabled, setTradingEnabled] = useState(false);
  const [restMarkets, setRestMarkets] = useState<Market[]>([]);
  const { width, containerRef, mounted } = useContainerWidth();
  const [height, setHeight] = useState(0);
  const ws = useMarketWs(symbol);
  const feed = useTradingReady({ connected: ws.connected });

  const deskTradingEnabled = ws.trading_enabled || tradingEnabled;

  const slipFrac = useCallback(() => {
    const n = parseFloat(loadSlipPct());
    return Number.isFinite(n) && n > 0 ? n / 100 : 0.01;
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setHeight(el.clientHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [mounted, containerRef]);

  useEffect(() => {
    api.health().then((h) => setTradingEnabled(h.trading_enabled)).catch(() => {});
  }, []);

  useEffect(() => {
    const load = () => api.markets().then(setRestMarkets).catch(() => {});
    load();
    const id = setInterval(load, 20_000);
    return () => clearInterval(id);
  }, []);

  const markets = useMemo(() => {
    const byIndex = new Map<number, Market>();
    for (const m of restMarkets) {
      if (m?.market_index == null) continue;
      byIndex.set(m.market_index, m);
    }
    for (const m of ws.markets) {
      if (m?.market_index == null) continue;
      const prev = byIndex.get(m.market_index);
      byIndex.set(m.market_index, prev ? { ...prev, ...m } : m);
    }
    return [...byIndex.values()];
  }, [ws.markets, restMarkets]);

  const market = useMemo(
    () => preferPerpMarket(markets, symbol) ?? null,
    [markets, symbol]
  );

  const rowHeight = useMemo(() => {
    if (height <= 0) return 16;
    return Math.max(8, (height - PAD * 2 - (GRID_ROWS - 1) * MARGIN) / GRID_ROWS);
  }, [height]);

  const filteredLayout = useMemo(
    () => layout.filter((l) => visible[l.i] !== false),
    [layout, visible]
  );

  const hiddenPanels = useMemo(
    () => PANEL_IDS.filter((id) => visible[id] === false),
    [visible]
  );

  const gridLayout = useMemo(
    () =>
      filteredLayout.map((item) => ({
        ...item,
        isDraggable: editing,
        isResizable: editing,
      })),
    [filteredLayout, editing]
  );

  const persistLayout = useCallback(
    (next: readonly LayoutItem[]) => {
      if (!editing) return;
      setLayout((prev) => {
        const known = new Set<string>(PANEL_IDS);
        const byId = new Map(
          next.filter((item) => known.has(item.i)).map((item) => [item.i, geometryOf(item)])
        );
        const merged = prev
          .filter((item) => known.has(item.i))
          .map((item) => byId.get(item.i) ?? item);
        for (const item of next) {
          if (!known.has(item.i)) continue;
          if (!merged.some((m) => m.i === item.i)) merged.push(geometryOf(item));
        }
        if (layoutsEqual(prev, merged)) return prev;
        localStorage.setItem(LAYOUT_KEY, JSON.stringify(merged));
        return merged;
      });
    },
    [editing]
  );

  const setPanelVisible = useCallback((id: PanelId, show: boolean) => {
    setVisible((prev) => {
      const next = { ...prev, [id]: show };
      localStorage.setItem(VISIBILITY_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const hidePanel = useCallback(
    (id: PanelId) => setPanelVisible(id, false),
    [setPanelVisible]
  );

  const showPanel = useCallback(
    (id: PanelId) => setPanelVisible(id, true),
    [setPanelVisible]
  );

  const panelClose = useCallback(
    (id: PanelId) => (editing ? () => hidePanel(id) : undefined),
    [editing, hidePanel]
  );

  const handleOverlayAction = useCallback(
    async (action: OverlayAction, overlay: ChartOverlay) => {
      if (action.action === "cancel") {
        if (overlay.kind === "algo") {
          try {
            const book = await api.algoStop(overlay.algoId);
            setAlgo(book);
            notifyOk(overlay.algoId ? `${overlay.algoId} stopped` : "Algo stopped");
          } catch (e) {
            notifyErr(e instanceof Error ? e.message : "Stop failed");
          }
          return;
        }
        if (overlay.marketIndex == null || overlay.orderIndex == null) return;
        try {
          await api.cancelOrder(overlay.marketIndex, overlay.orderIndex);
          notifyOk("Order cancelled");
        } catch (e) {
          notifyErr(e instanceof Error ? e.message : "Cancel failed");
        }
        return;
      }
      if (!tradingEnabled) {
        notifyErr("Trading not configured");
        return;
      }
      if (!feed.ready) {
        notifyErr(feed.reason ?? "Feed not ready");
        return;
      }
      if (overlay.marketIndex == null || overlay.size == null || overlay.size <= 0 || !overlay.side) {
        return;
      }
      const closeSide = overlay.side === "buy" ? "sell" : "buy";
      const size = String(overlay.size);
      const slip = slipFrac();
      try {
        if (action.action === "close") {
          await api.placeMarketOrder(
            {
              market_index: overlay.marketIndex,
              side: closeSide,
              size,
              slippage: slip,
              reduce_only: true,
            },
          );
          notifyOk("Position closed");
        } else if (action.action === "reverse") {
          try {
            await api.placeMarketOrder(
              {
                market_index: overlay.marketIndex,
                side: closeSide,
                size,
                slippage: slip,
                reduce_only: true,
              },
            );
          } catch (e) {
            notifyErr(e instanceof Error ? e.message : "Close leg failed");
            return;
          }
          try {
            await api.placeMarketOrder(
              {
                market_index: overlay.marketIndex,
                side: closeSide,
                size,
                slippage: slip,
                reduce_only: false,
              },
            );
            notifyOk("Position reversed");
          } catch (e) {
            notifyErr(e instanceof Error ? e.message : "Closed — reverse open failed");
          }
        }
      } catch (e) {
        notifyErr(e instanceof Error ? e.message : "Order failed");
      }
    },
    [feed.ready, feed.reason, slipFrac, tradingEnabled]
  );

  const resetLayout = () => {
    const allVisible = defaultPanelVisibility();
    setLayout(DEFAULT_LAYOUT);
    setVisible(allVisible);
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(DEFAULT_LAYOUT));
    localStorage.setItem(VISIBILITY_KEY, JSON.stringify(allVisible));
    notifyOk("Layout reset");
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <Header
        markets={markets}
        symbol={symbol}
        onSymbolChange={setSymbol}
        network={ws.network}
        connected={ws.connected}
        tradingEnabled={deskTradingEnabled}
        editing={editing}
        onEditToggle={() => setEditing((open) => !open)}
      />

      {editing && (
        <div className="flex shrink-0 items-center gap-2 border-b border-rule bg-panel px-3 py-1">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
            {hiddenPanels.length === 0 ? (
              <span className="text-[11px] text-muted">All panels on the desk</span>
            ) : (
              hiddenPanels.map((id) => (
                <Button
                  key={id}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => showPanel(id)}
                >
                  + {PANEL_CATALOG[id]}
                </Button>
              ))
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button type="button" variant="ghost" size="sm" onClick={resetLayout}>
              Reset
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="font-semibold text-text"
              onClick={() => setEditing(false)}
            >
              Done
            </Button>
          </div>
        </div>
      )}

      <div ref={containerRef} className="relative min-h-0 flex-1 overflow-hidden">
        {mounted && height > 0 && (
          <GridLayout
            className={editing ? "layout" : "layout layout-locked"}
            layout={gridLayout}
            width={width}
            autoSize
            gridConfig={{
              cols: GRID_COLS,
              rowHeight,
              margin: [MARGIN, MARGIN],
              containerPadding: [PAD, PAD],
              maxRows: GRID_ROWS,
            }}
            dragConfig={{
              enabled: editing,
              handle: ".panel-drag",
              cancel: "input, textarea, button, select, a",
              bounded: true,
              threshold: 3,
            }}
            resizeConfig={{
              enabled: editing,
              handles: ["se", "e", "s", "w", "n", "sw", "ne", "nw"],
            }}
            compactor={verticalCompactor}
            onLayoutChange={persistLayout}
          >
            {visible.chart !== false && (
              <div key="chart" className="h-full">
                <WidgetShell>
                  <ChartPanel
                    symbol={symbol}
                    market={market}
                    tradingEnabled={deskTradingEnabled}
                    connected={ws.connected}
                    onOverlayAction={handleOverlayAction}
                    onClose={panelClose("chart")}
                  />
                </WidgetShell>
              </div>
            )}
            {visible.book !== false && (
              <div key="book" className="h-full">
                <WidgetShell>
                  <OrderBookWidget onClose={panelClose("book")} />
                </WidgetShell>
              </div>
            )}
            {visible.tape !== false && (
              <div key="tape" className="h-full">
                <WidgetShell>
                  <TradesTapeWidget onClose={panelClose("tape")} />
                </WidgetShell>
              </div>
            )}
            {visible.ticket !== false && (
              <div key="ticket" className="h-full">
                <WidgetShell>
                  <OrderTicket
                    market={market}
                    tradingEnabled={deskTradingEnabled}
                    connected={ws.connected}
                    onClose={panelClose("ticket")}
                  />
                </WidgetShell>
              </div>
            )}
            {visible.alerts !== false && (
              <div key="alerts" className="h-full">
                <WidgetShell>
                  <AlertsPanel onOpenPair={setPair} onClose={panelClose("alerts")} />
                </WidgetShell>
              </div>
            )}
            {visible.liqs !== false && (
              <div key="liqs" className="h-full">
                <WidgetShell>
                  <LiqsPanel onOpenPair={setPair} onClose={panelClose("liqs")} />
                </WidgetShell>
              </div>
            )}
            {visible.positions !== false && (
              <div key="positions" className="h-full">
                <WidgetShell>
                  <PositionsPanel
                    market={market}
                    markets={markets}
                    tradingEnabled={deskTradingEnabled}
                    connected={ws.connected}
                    onSymbolChange={setSymbol}
                    onClose={panelClose("positions")}
                  />
                </WidgetShell>
              </div>
            )}
          </GridLayout>
        )}
      </div>
    </div>
  );
}
