/* oxlint-disable react-hooks/exhaustive-deps, react/immutability -- effects moved unchanged */
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type MouseEventParams,
} from "lightweight-charts";
import { useEffect, type Dispatch, type RefObject, type SetStateAction } from "react";

import { FillMarksPrimitive, type FillSpot } from "@/lib/fillMarkPrimitive";
import { isSettled } from "@/lib/funding";
import { parseOverlayAction, TradingLinesPrimitive, type ChartOverlay } from "@/lib/chartTradingLines";
import { keyBlocked } from "@/lib/keyTarget";
import { snapTick, type DraftMove } from "@/lib/ticketAmend";
import { TopOfBookPrimitive } from "@/lib/chartTopOfBook";
import { getQuickSize } from "@/lib/quickSizes";
import { createTicketAmend, type TicketAmendHost } from "@/lib/ticketAmend";
import { createTicketPlace } from "@/lib/ticketPlace";
import { theme } from "@/lib/theme";
import { formatSize } from "@/lib/utils";

import { applyVolumeLayout, priceFormat } from "./chartFormat";
import { RIGHT_OFFSET } from "./chartPrefs";
import { ohlcOf, sameOhlc, type Ohlc } from "./chartFormat";

export type QtyEditState = {
  overlayId: string;
  marketIndex: number;
  orderIndex: string;
  price: number;
  color: string;
  initial: string;
  rect: { x: number; y: number; w: number; h: number };
};

export type ChartHover = {
  key: string;
  bar: Ohlc;
  oi: number | null;
  fund: { apr: number; settled: boolean } | null;
  time: number | null;
};

function chartPoint(el: HTMLElement, e: PointerEvent) {
  const r = el.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

function chartRegion(
  chart: IChartApi,
  pt: { x: number; y: number }
): "axis" | "pane" | "elsewhere" {
  let paneW = 0;
  let paneH = 0;
  try {
    const pane = chart.paneSize();
    paneW = pane?.width ?? 0;
    paneH = pane?.height ?? 0;
  } catch {
    return "elsewhere";
  }
  if (!(paneW > 0) || !(paneH > 0) || pt.x < 0 || pt.y < 0 || pt.y > paneH) return "elsewhere";
  if (pt.x >= paneW) return "axis";
  return "pane";
}

function axisGhost(price: number, side: "buy" | "sell"): ChartOverlay {
  const qty = getQuickSize();
  const n = parseFloat(qty);
  const size = Number.isFinite(n) && n > 0 ? formatSize(n) : "";
  return {
    id: "axis-ghost",
    kind: "order",
    price,
    color: side === "buy" ? theme.bid : theme.ask,
    label: size ? `${side === "buy" ? "BUY" : "SELL"} ${size}` : side === "buy" ? "BUY" : "SELL",
    side,
    interactive: false,
  };
}

type Refs = {
  isPrice: boolean;
  priceDecimals: number;
  setHover: Dispatch<SetStateAction<ChartHover | null>>;
  setQtyEdit: Dispatch<SetStateAction<QtyEditState | null>>;
  containerRef: RefObject<HTMLDivElement | null>;
  wrapRef: RefObject<HTMLDivElement | null>;
  chartRef: RefObject<IChartApi | null>;
  seriesRef: RefObject<ISeriesApi<"Candlestick"> | null>;
  fillMarksRef: RefObject<FillMarksPrimitive | null>;
  volSeriesRef: RefObject<ISeriesApi<"Histogram"> | null>;
  oiSeriesRef: RefObject<ISeriesApi<"Line"> | null>;
  fundSeriesRef: RefObject<ISeriesApi<"Histogram"> | null>;
  tradingLinesRef: RefObject<TradingLinesPrimitive | null>;
  topOfBookRef: RefObject<TopOfBookPrimitive | null>;
  overlaysRef: RefObject<ChartOverlay[]>;
  topRef: RefObject<ReturnType<typeof import("@/lib/liveData").useLiveTopOfBook>>;
  bboOnRef: RefObject<boolean>;
  onActionRef: RefObject<((action: import("@/lib/chartTradingLines").OverlayAction, overlay: ChartOverlay) => void) | undefined>;
  onAmendRef: RefObject<((amend: import("@/lib/ticketAmend").TicketAmend) => void) | undefined>;
  onPlaceRef: RefObject<((place: import("@/lib/ticketPlace").TicketPlace) => void) | undefined>;
  livePriceRef: RefObject<number | null>;
  priceDecimalsRef: RefObject<number>;
  amendRef: RefObject<ReturnType<typeof createTicketAmend> | null>;
  placeRef: RefObject<ReturnType<typeof createTicketPlace> | null>;
  ghostRef: RefObject<ChartOverlay | null>;
  suppressClickRef: RefObject<boolean>;
  sizeClickRef: RefObject<ChartOverlay | null>;
  paintLinesRef: RefObject<() => void>;
  axisArmedRef: RefObject<boolean>;
  planArmedRef: RefObject<boolean>;
  onPlanClickRef: RefObject<((price: number) => void) | undefined>;
  onDraftMoveRef: RefObject<((move: DraftMove) => void) | undefined>;
  onDraftClearRef: RefObject<() => void>;
  onDraftEnterRef: RefObject<() => boolean>;
  volOnRef: RefObject<boolean>;
  primedRef: RefObject<boolean>;
  lastMetaRef: RefObject<{ first: number; time: number; len: number } | null>;
  seriesKeyRef: RefObject<string>;
  fillSpotRef: RefObject<FillSpot[]>;
};

export function useChartTicketInteraction(input: Refs) {
  const {
    isPrice, priceDecimals, setHover, setQtyEdit,
    containerRef, wrapRef, chartRef, seriesRef, fillMarksRef, volSeriesRef,
    oiSeriesRef, fundSeriesRef, tradingLinesRef, topOfBookRef, overlaysRef,
    topRef, bboOnRef, onActionRef, onAmendRef, onPlaceRef, livePriceRef,
    priceDecimalsRef, amendRef, placeRef, ghostRef, suppressClickRef,
    sizeClickRef, paintLinesRef, axisArmedRef, planArmedRef, onPlanClickRef,
    onDraftMoveRef, onDraftClearRef, onDraftEnterRef, volOnRef, primedRef,
    lastMetaRef, seriesKeyRef, fillSpotRef,
  } = input;
  useEffect(() => {
    if (!isPrice) return;
    if (!containerRef.current || !wrapRef.current) return;

    const wrap = wrapRef.current;
    const chart = createChart(containerRef.current, {
      width: wrap.clientWidth,
      height: wrap.clientHeight,
      localization: { locale: theme.chartLocale },
      layout: {
        background: { color: theme.panel },
        textColor: theme.muted,
        fontFamily: theme.fontMono,
        fontSize: theme.chartFontSize,
      },
      grid: {
        vertLines: { color: theme.rule },
        horzLines: { color: theme.rule },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: theme.rule,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: theme.rule,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: RIGHT_OFFSET,
        shiftVisibleRangeOnNewBar: true,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: theme.bid,
      downColor: theme.ask,
      borderUpColor: theme.bid,
      borderDownColor: theme.ask,
      wickUpColor: theme.bid,
      wickDownColor: theme.ask,
      priceFormat: priceFormat(priceDecimals),
    });
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    applyVolumeLayout(series, volOnRef.current);

    chartRef.current = chart;
    seriesRef.current = series;
    const fillMarksPrimitive = new FillMarksPrimitive();
    series.attachPrimitive(fillMarksPrimitive);
    fillMarksRef.current = fillMarksPrimitive;
    fillMarksPrimitive.setMarks(fillSpotRef.current);
    volSeriesRef.current = vol;
    primedRef.current = false;
    lastMetaRef.current = null;

    const tradingLines = new TradingLinesPrimitive();
    series.attachPrimitive(tradingLines);
    tradingLinesRef.current = tradingLines;

    const topOfBook = new TopOfBookPrimitive();
    series.attachPrimitive(topOfBook);
    topOfBookRef.current = topOfBook;
    topOfBook.setTop(bboOnRef.current ? topRef.current : null);

    const paintLines = () => {
      const lines: ChartOverlay[] = [];
      for (const o of overlaysRef.current) {
        if (!Number.isFinite(o.price) || o.price <= 0) continue;
        lines.push(o);
      }
      const preview = amendRef.current?.preview();
      const painted = preview
        ? lines.map((o) => (o.id === preview.overlayId ? { ...o, price: preview.price } : o))
        : lines;
      const ghost = ghostRef.current;
      tradingLines.setLines(ghost ? [...painted, ghost] : painted);
    };
    paintLinesRef.current = paintLines;

    const host: TicketAmendHost & {
      regionAt: (pt: { x: number; y: number }) => "axis" | "pane" | "elsewhere";
    } = {
      priceAtY(y) {
        const px = series.coordinateToPrice(y);
        return px != null && Number.isFinite(px) ? px : null;
      },
      setPanEnabled(enabled) {
        chart.applyOptions({ handleScroll: enabled, handleScale: enabled });
      },
      hit(pt) {
        return tradingLines.hitAt(pt.x, pt.y);
      },
      regionAt(pt) {
        return chartRegion(chart, pt);
      },
    };

    const amend = createTicketAmend(host, {
      onAmend: (a) => onAmendRef.current?.(a),
      onDraft: (move) => onDraftMoveRef.current?.(move),
    });
    amend.setPriceDecimals(priceDecimalsRef.current);
    amend.setOverlays(overlaysRef.current);
    amendRef.current = amend;

    const place = createTicketPlace(host, {
      onPlace: (p) => onPlaceRef.current?.(p),
    });
    place.setPriceDecimals(priceDecimalsRef.current);
    place.setLivePrice(livePriceRef.current);
    place.setArmed(axisArmedRef.current);
    placeRef.current = place;

    const el = containerRef.current;
    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0 || !el) return;
      const pt = chartPoint(el, e);
      const sizeHit = tradingLines.hitAt(pt.x, pt.y);
      if (
        sizeHit?.region === "size" &&
        sizeHit.overlay.qtyEditable &&
        !amend.isLocked(sizeHit.overlay.id)
      ) {
        sizeClickRef.current = sizeHit.overlay;
        suppressClickRef.current = true;
        return;
      }
      sizeClickRef.current = null;
      if (amend.pointerDown(pt)) {
        suppressClickRef.current = true;
        try {
          el.setPointerCapture(e.pointerId);
        } catch {
          /* ignore */
        }
        paintLines();
        return;
      }
      place.pointerDown(pt);
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!el) return;
      const pt = chartPoint(el, e);
      amend.pointerMove(pt);
      place.pointerMove(pt);
      const hover = place.hover(pt);
      ghostRef.current = hover ? axisGhost(Number(hover.price), hover.side) : null;
      const region = host.regionAt(pt);
      const hit = tradingLines.hitAt(pt.x, pt.y);
      if (amend.preview()) el.style.cursor = "ns-resize";
      else if (
        hit?.region === "size" &&
        hit.overlay.qtyEditable &&
        !amend.isLocked(hit.overlay.id)
      ) {
        el.style.cursor = "text";
      } else if (axisArmedRef.current && region === "axis") el.style.cursor = "ns-resize";
      else el.style.cursor = "";
      paintLines();
    };
    const finishPointer = (e: PointerEvent) => {
      if (!el) return;
      const pt = chartPoint(el, e);
      const pendingSize = sizeClickRef.current;
      sizeClickRef.current = null;
      amend.pointerUp();
      place.pointerUp(pt);
      if (
        pendingSize &&
        pendingSize.marketIndex != null &&
        pendingSize.orderIndex != null &&
        pendingSize.qtyLabel
      ) {
        const rect = tradingLines.qtyHitRect(pendingSize.id);
        if (rect) {
          setQtyEdit({
            overlayId: pendingSize.id,
            marketIndex: pendingSize.marketIndex,
            orderIndex: pendingSize.orderIndex,
            price: pendingSize.price,
            color: pendingSize.color,
            initial: pendingSize.qtyLabel,
            rect,
          });
        }
      }
      try {
        el.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      paintLines();
    };
    const onPointerCancel = () => {
      sizeClickRef.current = null;
      amend.pointerCancel();
      place.pointerCancel();
      ghostRef.current = null;
      if (el) el.style.cursor = "";
      paintLines();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setQtyEdit(null);
        sizeClickRef.current = null;
        amend.pointerCancel();
        place.pointerCancel();
        ghostRef.current = null;
        paintLines();
        if (!keyBlocked(e.target)) onDraftClearRef.current();
        return;
      }
      if (e.key === "Enter" && planArmedRef.current && !e.repeat && !keyBlocked(e.target)) {
        if (onDraftEnterRef.current()) e.preventDefault();
      }
    };
    el?.addEventListener("pointerdown", onPointerDown);
    el?.addEventListener("pointermove", onPointerMove);
    el?.addEventListener("pointerup", finishPointer);
    el?.addEventListener("pointercancel", onPointerCancel);
    document.addEventListener("keydown", onKeyDown);
    paintLines();

    const onClick = (param: MouseEventParams) => {
      if (suppressClickRef.current) {
        suppressClickRef.current = false;
        return;
      }
      const action = parseOverlayAction(param.hoveredInfo?.objectId ?? param.hoveredObjectId);
      if (action) {
        const overlay = overlaysRef.current.find((o) => o.id === action.id);
        if (overlay) onActionRef.current?.(action, overlay);
        return;
      }
      if (!planArmedRef.current || param.point == null) return;
      if (chartRegion(chart, param.point) !== "pane") return;
      const raw = series.coordinateToPrice(param.point.y);
      if (raw == null || !Number.isFinite(raw)) return;
      const snapped = snapTick(raw, priceDecimalsRef.current);
      if (!snapped) return;
      onPlanClickRef.current?.(Number(snapped));
    };
    chart.subscribeClick(onClick);

    const onMove = (param: MouseEventParams) => {
      const key = seriesKeyRef.current;
      if (!param.time) {
        setHover((h) => (h == null || h.key !== key ? h : null));
        return;
      }
      const barTime = typeof param.time === "number" ? param.time : null;
      const raw = param.seriesData.get(series);
      if (raw && "open" in raw && "close" in raw) {
        const rawVol = param.seriesData.get(vol);
        const volVal =
          volOnRef.current && rawVol && "value" in rawVol
            ? (rawVol as HistogramData).value
            : undefined;
        const next = ohlcOf(raw as CandlestickData, volVal);
        const oiSeries = oiSeriesRef.current;
        const rawOi = oiSeries ? param.seriesData.get(oiSeries) : undefined;
        const oi =
          rawOi && "value" in rawOi && typeof rawOi.value === "number" && Number.isFinite(rawOi.value)
            ? rawOi.value
            : null;
        const fundSeries = fundSeriesRef.current;
        const rawFund = fundSeries ? param.seriesData.get(fundSeries) : undefined;
        const fund =
          rawFund &&
          "value" in rawFund &&
          typeof rawFund.value === "number" &&
          Number.isFinite(rawFund.value)
            ? { apr: rawFund.value, settled: isSettled(rawFund) }
            : null;
        setHover((prev) => {
          if (!next) return prev?.key === key ? null : prev;
          if (
            prev?.key === key &&
            prev.time === barTime &&
            sameOhlc(prev.bar, next) &&
            prev.oi === oi &&
            prev.fund?.apr === fund?.apr &&
            prev.fund?.settled === fund?.settled
          ) {
            return prev;
          }
          return { key, bar: next, oi, fund, time: barTime };
        });
      }
    };
    chart.subscribeCrosshairMove(onMove);

    let lastW = wrap.clientWidth;
    let lastH = wrap.clientHeight;
    const ro = new ResizeObserver(() => {
      const el = wrapRef.current;
      if (!el) return;
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w < 1 || h < 1 || (w === lastW && h === lastH)) return;
      lastW = w;
      lastH = h;
      chart.applyOptions({ width: w, height: h });
    });
    ro.observe(wrap);

    return () => {
      ro.disconnect();
      el?.removeEventListener("pointerdown", onPointerDown);
      el?.removeEventListener("pointermove", onPointerMove);
      el?.removeEventListener("pointerup", finishPointer);
      el?.removeEventListener("pointercancel", onPointerCancel);
      document.removeEventListener("keydown", onKeyDown);
      amend.destroy();
      place.destroy();
      amendRef.current = null;
      placeRef.current = null;
      paintLinesRef.current = () => {};
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      fillMarksRef.current = null;
      volSeriesRef.current = null;
      oiSeriesRef.current = null;
      fundSeriesRef.current = null;
      tradingLinesRef.current = null;
      topOfBookRef.current = null;
    };
    // Recreate when returning to the price chart; format is applied below.
    // oxlint-disable-next-line exhaustive-deps
  }, [isPrice]);
}
