import { lazy, Suspense, useEffect, useMemo, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from "react";
import { SquareArrowOutUpRight } from "lucide-react";

import { PanelCloseButton } from "@/components/desk/PanelHeader";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { OrderRemainingEditor } from "@/components/widgets/OrderRemainingEditor";
import type { ScanTab } from "@/components/widgets/ScanBoard";
import { TimeframePins } from "@/components/widgets/TimeframePins";
import type { Candle, LiquidationSummaryHours, Market } from "@/lib/api";
import { openWatchWindow } from "@/lib/deskBridge";
import type { FillMark } from "@/lib/fillMarks";
import { isSettled, type FundingBar } from "@/lib/funding";
import { rankRelativeStrength } from "@/lib/relativeStrength";
import { snapTick, type TicketAmend } from "@/lib/ticketAmend";
import { theme } from "@/lib/theme";
import {
  draftReady,
  requestChartDraftOpen,
  useChartDraft,
  useChartDraftNotice,
  useChartPlan,
} from "@/lib/chartDraft";
import { subscribeHotkeys } from "@/lib/hotkeys";
import { parseTimeframe, persistPins, persistTimeframe, supportsOpenInterest } from "@/lib/timeframe";
import { WATCH_WINDOWS, WATCH_WINDOW_SEC, persistWatchWindow, type WatchWindow } from "@/lib/watchWindow";

import {
  BBO_KEY,
  CHART_MODES,
  FUND_KEY,
  MAYREKT_KEY,
  MODE_KEY,
  OI_KEY,
  SCAN_TAB_KEY,
  SCAN_TABS,
  VOL_KEY,
  type ChartMode,
} from "./chartPrefs";
import { ohlcOf } from "./chartFormat";
import { LiqsReadout, NumeraireReadout, OhlcReadout } from "./Readouts";
import type { QtyEditState } from "./useChartTicketInteraction";

const ScanBoard = lazy(() =>
  import("@/components/widgets/ScanBoard").then((m) => ({ default: m.ScanBoard })),
);
const WatchBoard = lazy(() =>
  import("@/components/widgets/WatchBoard").then((m) => ({ default: m.WatchBoard })),
);

function BoardFallback({ title, detail }: { title: string; detail: string }) {
  return (
    <Empty className="h-full rounded-none border-0">
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{detail}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export function ChartFrame(props: {
  symbol: string;
  markets: readonly Market[];
  onSymbolChange?: (symbol: string) => void;
  onClose?: () => void;
  children?: ReactNode;
  priceDecimals: number;
  tf: string;
  setTf: (next: string) => void;
  pins: string[];
  setPins: (next: string[]) => void;
  mode: ChartMode;
  setMode: (next: ChartMode) => void;
  scanTab: ScanTab;
  setScanTab: (next: ScanTab) => void;
  watchWindow: WatchWindow;
  setWatchWindow: (next: WatchWindow) => void;
  volOn: boolean;
  setVolOn: Dispatch<SetStateAction<boolean>>;
  oiOn: boolean;
  setOiOn: Dispatch<SetStateAction<boolean>>;
  fundOn: boolean;
  setFundOn: Dispatch<SetStateAction<boolean>>;
  bboOn: boolean;
  setBboOn: Dispatch<SetStateAction<boolean>>;
  mayRektOn: boolean;
  setMayRektOn: Dispatch<SetStateAction<boolean>>;
  axisArmed: boolean;
  setAxisArmed: (next: boolean) => void;
  quickOn: boolean;
  setQuickOn: (next: boolean) => void;
  liqHours: LiquidationSummaryHours;
  setLiqHours: (hours: LiquidationSummaryHours) => void;
  isPrice: boolean;
  isScan: boolean;
  isWatch: boolean;
  popped: boolean;
  showOi: boolean;
  showFund: boolean;
  bar: { label: string; seconds: number };
  wrapRef: RefObject<HTMLDivElement | null>;
  containerRef: RefObject<HTMLDivElement | null>;
  shownQtyEdit: QtyEditState | null;
  setQtyEdit: Dispatch<SetStateAction<QtyEditState | null>>;
  marketByIndex: Map<number, Market>;
  amendRef: RefObject<{ lock: (id: string) => void } | null>;
  onAmendRef: RefObject<((amend: TicketAmend) => void) | undefined>;
  display: Candle[];
  hover: { key: string; bar: { open: number; high: number; low: number; close: number; volume?: number }; oi: number | null; fund: { apr: number; settled: boolean } | null; time: number | null } | null;
  hoverBar: { open: number; high: number; low: number; close: number; volume?: number } | null;
  seriesKey: string;
  liveOi: number | null;
  fundBars: FundingBar[];
  hoverFills: FillMark[];
}) {
  const {
    symbol, markets, onSymbolChange, onClose, children, priceDecimals,
    tf, setTf, pins, setPins, mode, setMode, scanTab, setScanTab,
    watchWindow, setWatchWindow, volOn, setVolOn, oiOn, setOiOn, fundOn, setFundOn,
    bboOn, setBboOn, mayRektOn, setMayRektOn, axisArmed, setAxisArmed, quickOn, setQuickOn,
    liqHours, setLiqHours, isPrice, isScan, isWatch, popped, showOi, showFund, bar,
    wrapRef, containerRef, shownQtyEdit, setQtyEdit, marketByIndex, amendRef, onAmendRef,
    display, hover, hoverBar, seriesKey, liveOi, fundBars, hoverFills,
  } = props;
  const { armed: planArmed, setArmed: setPlanArmed } = useChartPlan();
  const draft = useChartDraft(symbol);
  const draftNote = useChartDraftNotice(symbol);
  const canOpenDraft = planArmed && draftReady(draft);
  const selectTf = (next: string) => {
    const parsed = parseTimeframe(next);
    if (!parsed || parsed.label === tf) return;
    setTf(parsed.label);
    persistTimeframe(parsed.label);
  };

  const changePins = (next: string[]) => {
    setPins(next);
    persistPins(next);
  };

  const selectMode = (next: ChartMode) => {
    if (next === mode) return;
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => subscribeHotkeys((id) => {
    if (id === "chart") selectMode("price");
    else if (id === "scan") selectMode("scan");
    else if (id === "watch") selectMode("watch");
    else if (id.startsWith("tf-")) {
      const label = pins[Number(id.slice(3)) - 1];
      if (label) selectTf(label);
    }
  }));

  const selectScanTab = (next: ScanTab) => {
    if (next === scanTab) return;
    setScanTab(next);
    try {
      localStorage.setItem(SCAN_TAB_KEY, next);
    } catch {
      /* ignore */
    }
  };

  const selectWatchWindow = (next: WatchWindow) => {
    if (next === watchWindow) return;
    setWatchWindow(next);
    persistWatchWindow(next);
  };

  const lastBar = display.length ? ohlcOf(display[display.length - 1]) : null;
  const ohlc = hoverBar ?? lastBar;
  const hovered = hover?.key === seriesKey ? hover : null;
  const oiRead = hovered ? hovered.oi : liveOi;
  const lastFund = fundBars[fundBars.length - 1];
  const fundRead = hovered
    ? hovered.fund
    : lastFund && "value" in lastFund
      ? { apr: lastFund.value, settled: isSettled(lastFund) }
      : null;
  const numeraireChange24h = useMemo(
    () => rankRelativeStrength(markets).numeraireChange24h,
    [markets]
  );

  const toggleVol = () => {
    setVolOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(VOL_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleFund = () => {
    setFundOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(FUND_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleOi = () => {
    setOiOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(OI_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleBbo = () => {
    setBboOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(BBO_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleMayRekt = () => {
    setMayRektOn((on) => {
      const next = !on;
      try {
        localStorage.setItem(MAYREKT_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="panel-drag grid h-8 shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center border-b border-border">
        <div className="flex min-w-0 items-center gap-px overflow-hidden px-1">
          {isPrice ? (
            <>
              <Toggle
                variant="seg"
                size="sm"
                pressed={volOn}
                title={volOn ? "Hide volume" : "Show volume"}
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleVol()}
              >
                Vol
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={showOi}
                disabled={!supportsOpenInterest(bar)}
                title={
                  supportsOpenInterest(bar)
                    ? oiOn
                      ? "Hide open interest"
                      : "Show open interest"
                    : "Open interest follows 1m, 5m, 15m, 1h, 4h, and 1d"
                }
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleOi()}
              >
                OI
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={showFund}
                disabled={!supportsOpenInterest(bar)}
                title={
                  supportsOpenInterest(bar)
                    ? fundOn
                      ? "Hide funding"
                      : "Show funding, APR. Faint bars are the estimate for an hour that has not settled"
                    : "Funding follows 1m, 5m, 15m, 1h, 4h, and 1d"
                }
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleFund()}
              >
                Fund
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={bboOn}
                title="Top of book"
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleBbo()}
              >
                B/A
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={mayRektOn}
                title={mayRektOn ? "Hide MayRekt" : "MayRekt"}
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={() => toggleMayRekt()}
              >
                MR
              </Toggle>
              <span className="mx-1 h-3 w-px shrink-0 bg-border" aria-hidden />
              <Toggle
                variant="seg"
                size="sm"
                pressed={axisArmed}
                title="Rest a Ticket on the price axis at Quick size. Below live price buys, above sells."
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={(next) => setAxisArmed(next)}
              >
                Axis
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={planArmed}
                title="Draw a Draft: click the entry, then the stop. Esc clears it. Nothing is sent until Start."
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={(next) => setPlanArmed(next)}
              >
                Plan
              </Toggle>
              <Toggle
                variant="seg"
                size="sm"
                pressed={quickOn}
                title={quickOn ? "Hide quick trade" : "Quick trade"}
                className="h-6 px-1.5 font-mono text-sm"
                onPressedChange={(next) => setQuickOn(next)}
              >
                QT
              </Toggle>
            </>
          ) : isScan && scanTab === "liqs" ? (
            <LiqsReadout hours={liqHours} />
          ) : isScan && scanTab === "rel" ? (
            <NumeraireReadout change={numeraireChange24h} />
          ) : null}
        </div>
        <ToggleGroup
          type="single"
          size="sm"
          spacing={0}
          value={isWatch ? "watch" : mode === "scan" ? "scan" : "price"}
          className="bg-background"
          onValueChange={(v) => {
            if (v === "watch") {
              if (popped) openWatchWindow();
              else selectMode("watch");
              return;
            }
            if (v && (CHART_MODES as readonly string[]).includes(v)) {
              selectMode(v as ChartMode);
            }
          }}
        >
          <ToggleGroupItem
            value="price"
            title="Price chart"
            className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
          >
            Chart
          </ToggleGroupItem>
          <ToggleGroupItem
            value="scan"
            title="Scan: Rel vs BTC, liquidations, activity and tones"
            className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
          >
            Scan
          </ToggleGroupItem>
          <ToggleGroupItem
            value="watch"
            title={popped ? "Watch is in its own window" : "Watch: live percent paths"}
            className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
          >
            Watch
          </ToggleGroupItem>
        </ToggleGroup>
        <div className="flex min-w-0 items-center justify-end gap-px overflow-hidden pr-1">
          {isScan ? (
            <ToggleGroup
              type="single"
              size="sm"
              spacing={0}
              value={scanTab}
              onValueChange={(v) => {
                if (v && (SCAN_TABS as readonly string[]).includes(v)) {
                  selectScanTab(v as ScanTab);
                }
              }}
            >
              <ToggleGroupItem
                value="rel"
                title="Relative strength vs BTC"
                className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
              >
                Rel
              </ToggleGroupItem>
              <ToggleGroupItem
                value="liqs"
                title="Liquidations in window"
                className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
              >
                Liqs
              </ToggleGroupItem>
              <ToggleGroupItem
                value="act"
                title="Activity: what every liquid perp's tape shows now"
                className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
              >
                Act
              </ToggleGroupItem>
              <ToggleGroupItem
                value="tones"
                title="Tones: last closed bar blue or orange"
                className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
              >
                Tones
              </ToggleGroupItem>
            </ToggleGroup>
          ) : null}
          {isWatch ? (
            <>
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
                  className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
                >
                  {w}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <button
              type="button"
              title="Pop out Watch"
              className="inline-flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => {
                if (openWatchWindow()) selectMode("price");
              }}
            >
              <SquareArrowOutUpRight className="size-3.5" />
            </button>
          </>
          ) : null}
          {isPrice ? (
            <TimeframePins timeframe={tf} pins={pins} onSelect={selectTf} onPins={changePins} />
          ) : null}
          {onClose ? <PanelCloseButton onClose={onClose} /> : null}
        </div>
      </div>
      {isPrice && planArmed && (canOpenDraft || draftNote) ? (
        <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border px-2">
          {canOpenDraft ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="h-6 px-2 font-mono text-sm"
              onClick={() => requestChartDraftOpen()}
            >
              Open in Planner
            </Button>
          ) : null}
          {draftNote ? (
            <span className="min-w-0 truncate font-mono text-sm text-ask" title={draftNote}>
              {draftNote}
            </span>
          ) : null}
        </div>
      ) : null}
      <div ref={wrapRef} className="relative flex min-h-0 flex-1 flex-col">
        {isPrice ? (
          <>
            <div ref={containerRef} className="absolute inset-0" />
            {shownQtyEdit ? (
              <div
                className="absolute z-20"
                style={{
                  left: shownQtyEdit.rect.x,
                  top: shownQtyEdit.rect.y,
                  width: Math.max(shownQtyEdit.rect.w, 56),
                  height: shownQtyEdit.rect.h,
                }}
              >
                <OrderRemainingEditor
                  align="left"
                  initial={shownQtyEdit.initial}
                  decimals={marketByIndex.get(shownQtyEdit.marketIndex)?.size_decimals ?? 4}
                  style={{
                    fontFamily: theme.fontMono,
                    fontSize: theme.chartFontSize,
                    lineHeight: `${shownQtyEdit.rect.h}px`,
                    color: shownQtyEdit.color,
                    background: "rgba(14, 17, 22, 0.96)",
                    boxShadow: `inset 0 0 0 1px ${shownQtyEdit.color}`,
                  }}
                  onCancel={() => setQtyEdit(null)}
                  onCommit={(size) => {
                    const price = snapTick(shownQtyEdit.price, priceDecimals);
                    if (
                      price == null ||
                      shownQtyEdit.marketIndex == null ||
                      shownQtyEdit.orderIndex == null
                    ) {
                      setQtyEdit(null);
                      return;
                    }
                    amendRef.current?.lock(shownQtyEdit.overlayId);
                    setQtyEdit(null);
                    onAmendRef.current?.({
                      overlayId: shownQtyEdit.overlayId,
                      marketIndex: shownQtyEdit.marketIndex,
                      orderIndex: shownQtyEdit.orderIndex,
                      price,
                      size,
                    });
                  }}
                />
              </div>
            ) : null}
            <div className="pointer-events-none absolute top-1 left-1.5 z-10 max-w-[calc(100%-4.5rem)] overflow-hidden rounded-sm bg-card/90 px-1 py-0.5">
              <OhlcReadout
                bar={ohlc}
                decimals={priceDecimals}
                showVolume={volOn}
                showOi={showOi}
                oi={oiRead}
                showFund={showFund}
                fund={fundRead}
                fills={hoverFills}
              />
            </div>
            {children ? (
              <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
                {children}
              </div>
            ) : null}
          </>
        ) : isWatch ? (
          <Suspense
            fallback={
              <BoardFallback
                title="Add Markets to Watch"
                detail="Plot live Paths for up to 8 Markets."
              />
            }
          >
            <WatchBoard
              windowSec={WATCH_WINDOW_SEC[watchWindow]}
              markets={markets}
              symbol={symbol}
              onSymbolChange={onSymbolChange}
            />
          </Suspense>
        ) : (
          <Suspense
            fallback={
              <BoardFallback title="Scan" detail="Relative strength, liquidations, activity, tones." />
            }
          >
            <ScanBoard
              tab={scanTab}
              hours={liqHours}
              onHoursChange={setLiqHours}
              markets={markets}
              symbol={symbol}
              onSymbolChange={onSymbolChange}
            />
          </Suspense>
        )}
      </div>
    </div>
  );
}
