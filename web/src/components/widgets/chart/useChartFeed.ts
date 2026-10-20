/* oxlint-disable react-hooks/exhaustive-deps, react/immutability -- effects moved unchanged */
import { useEffect, type Dispatch, type RefObject, type SetStateAction } from "react";

import { api, type Candle, type OpenInterestSample } from "@/lib/api";
import { aggregateCandles } from "@/lib/chartCandles";
import type { ChartOverlay, OverlayAction, TradingLinesPrimitive } from "@/lib/chartTradingLines";
import { type FundingBar, type FundingSample } from "@/lib/funding";
import { seedCandles1s, setMinuteCandles } from "@/lib/liveData";
import type { OiLinePoint } from "@/lib/openInterest";
import { createTicketAmend, type TicketAmend } from "@/lib/ticketAmend";
import { createTicketPlace, type TicketPlace } from "@/lib/ticketPlace";
import { candleSource } from "@/lib/timeframe";

import type { QtyEditState } from "./useChartTicketInteraction";

type Bar = { label: string; seconds: number };

type Feed = {
  shownQtyEdit: QtyEditState | null;
  setQtyEdit: Dispatch<SetStateAction<QtyEditState | null>>;
  tradingLinesRef: RefObject<TradingLinesPrimitive | null>;
  oiLine: OiLinePoint[];
  fundBars: FundingBar[];
  oiLineRef: RefObject<OiLinePoint[]>;
  fundBarsRef: RefObject<FundingBar[]>;
  seriesKey: string;
  seriesKeyRef: RefObject<string>;
  overlays: ChartOverlay[];
  overlaysRef: RefObject<ChartOverlay[]>;
  amendRef: RefObject<ReturnType<typeof createTicketAmend> | null>;
  placeRef: RefObject<ReturnType<typeof createTicketPlace> | null>;
  ghostRef: RefObject<ChartOverlay | null>;
  onOverlayAction: ((action: OverlayAction, overlay: ChartOverlay) => void) | undefined;
  onTicketAmend: ((amend: TicketAmend) => void) | undefined;
  onTicketPlace: ((place: TicketPlace) => void) | undefined;
  onActionRef: RefObject<((action: OverlayAction, overlay: ChartOverlay) => void) | undefined>;
  onAmendRef: RefObject<((amend: TicketAmend) => void) | undefined>;
  onPlaceRef: RefObject<((place: TicketPlace) => void) | undefined>;
  livePrice: number | null;
  livePriceRef: RefObject<number | null>;
  priceDecimals: number;
  priceDecimalsRef: RefObject<number>;
  axisArmed: boolean;
  axisArmedRef: RefObject<boolean>;
  volOn: boolean;
  volOnRef: RefObject<boolean>;
  top: ReturnType<typeof import("@/lib/liveData").useLiveTopOfBook>;
  topRef: RefObject<ReturnType<typeof import("@/lib/liveData").useLiveTopOfBook>>;
  bboOn: boolean;
  bboOnRef: RefObject<boolean>;
  isPrice: boolean;
  fromSeconds: boolean;
  symbol: string;
  bar: Bar;
  tf: string;
  showOi: boolean;
  showFund: boolean;
  setHist: Dispatch<SetStateAction<{ key: string; candles: Candle[] }>>;
  setOiHist: Dispatch<SetStateAction<{ key: string; points: OpenInterestSample[] }>>;
  setFundHist: Dispatch<SetStateAction<{ key: string; points: FundingSample[] }>>;
  setNowSec: Dispatch<SetStateAction<number>>;
};

export function useChartFeed(input: Feed) {
  const {
    shownQtyEdit, setQtyEdit, tradingLinesRef, oiLine, fundBars, oiLineRef, fundBarsRef,
    seriesKey, seriesKeyRef, overlays, overlaysRef, amendRef, placeRef, ghostRef,
    onOverlayAction, onTicketAmend, onTicketPlace, onActionRef, onAmendRef,
    onPlaceRef, livePrice, livePriceRef, priceDecimals, priceDecimalsRef, axisArmed,
    axisArmedRef, volOn, volOnRef, top, topRef, bboOn, bboOnRef, isPrice, fromSeconds,
    symbol, bar, tf, showOi, showFund, setHist, setOiHist, setFundHist, setNowSec,
  } = input;
  useEffect(() => {
    tradingLinesRef.current?.setOmitQty(shownQtyEdit?.overlayId ?? null);
  }, [shownQtyEdit?.overlayId]);

  useEffect(() => {
    const id = shownQtyEdit?.overlayId;
    if (!id) return;
    let frame = 0;
    const tick = () => {
      const rect = tradingLinesRef.current?.qtyHitRect(id);
      if (rect) {
        setQtyEdit((prev) => {
          if (!prev || prev.overlayId !== id) return prev;
          if (
            prev.rect.x === rect.x &&
            prev.rect.y === rect.y &&
            prev.rect.w === rect.w &&
            prev.rect.h === rect.h
          ) {
            return prev;
          }
          return { ...prev, rect };
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [shownQtyEdit?.overlayId]);

  useEffect(() => {
    oiLineRef.current = oiLine;
  }, [oiLine]);

  useEffect(() => {
    fundBarsRef.current = fundBars;
  }, [fundBars]);

  useEffect(() => {
    seriesKeyRef.current = seriesKey;
  }, [seriesKey]);

  useEffect(() => {
    overlaysRef.current = overlays;
    amendRef.current?.setOverlays(overlays);
  }, [overlays]);

  useEffect(() => {
    onActionRef.current = onOverlayAction;
  }, [onOverlayAction]);

  useEffect(() => {
    onAmendRef.current = onTicketAmend;
  }, [onTicketAmend]);

  useEffect(() => {
    onPlaceRef.current = onTicketPlace;
  }, [onTicketPlace]);

  useEffect(() => {
    livePriceRef.current = livePrice;
    placeRef.current?.setLivePrice(livePrice);
  }, [livePrice]);

  useEffect(() => {
    priceDecimalsRef.current = priceDecimals;
    amendRef.current?.setPriceDecimals(priceDecimals);
    placeRef.current?.setPriceDecimals(priceDecimals);
  }, [priceDecimals]);

  useEffect(() => {
    axisArmedRef.current = axisArmed;
    placeRef.current?.setArmed(axisArmed);
    if (!axisArmed) {
      ghostRef.current = null;
    }
  }, [axisArmed]);

  useEffect(() => {
    volOnRef.current = volOn;
  }, [volOn]);

  useEffect(() => {
    topRef.current = top;
  }, [top]);

  useEffect(() => {
    bboOnRef.current = bboOn;
  }, [bboOn]);

  useEffect(() => {
    if (!isPrice || fromSeconds) return;
    const key = `${symbol}:${bar.label}`;
    const source = candleSource(bar);
    let cancelled = false;
    api
      .candles(symbol, source, 500)
      .then((data) => {
        if (cancelled) return;
        if (source === "1m") setMinuteCandles(data);
        const candles = source === bar.label ? data : aggregateCandles(data, bar.seconds);
        setHist({ key, candles });
      })
      .catch(() => {
        if (!cancelled) setHist({ key, candles: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, bar, fromSeconds, isPrice]);

  useEffect(() => {
    if (!isPrice || fromSeconds || candleSource(bar) === "1m") return;
    let cancelled = false;
    api
      .candles(symbol, "1m", 500)
      .then((data) => {
        if (!cancelled) setMinuteCandles(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [symbol, bar, fromSeconds, isPrice]);

  useEffect(() => {
    if (!isPrice || !fromSeconds) return;
    let cancelled = false;
    api
      .candles(symbol, "1s", 3600)
      .then((data) => {
        if (!cancelled && data.length) seedCandles1s(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [symbol, fromSeconds, isPrice]);

  useEffect(() => {
    if (!showOi) return;
    const key = `${symbol}:${tf}`;
    let cancelled = false;
    const load = () => {
      api
        .openInterest(symbol, tf, 500)
        .then((data) => {
          if (!cancelled) setOiHist({ key, points: data });
        })
        .catch(() => {
          if (!cancelled) setOiHist({ key, points: [] });
        });
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, tf, showOi]);

  useEffect(() => {
    if (!showFund) return;
    const key = `${symbol}:${tf}`;
    let cancelled = false;
    const load = () => {
      api
        .funding(symbol, tf, 500)
        .then((data) => {
          if (!cancelled) setFundHist({ key, points: data });
        })
        .catch(() => {
          if (!cancelled) setFundHist({ key, points: [] });
        });
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, tf, showFund]);

  useEffect(() => {
    if (!showOi && !showFund) return;
    const id = setInterval(() => setNowSec(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, [showOi, showFund]);
}
