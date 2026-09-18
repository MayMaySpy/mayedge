import type { ChartOverlay } from "@/lib/chartTradingLines";

export type TicketAmend = {
  overlayId: string;
  marketIndex: number;
  orderIndex: string;
  price: string;
};

export type TicketAmendHit = {
  overlay: ChartOverlay;
  region: "cancel" | "body";
};

export type TicketAmendHost = {
  priceAtY(y: number): number | null;
  setPanEnabled(enabled: boolean): void;
  hit(pt: { x: number; y: number }): TicketAmendHit | null;
};

export function snapTick(price: number, decimals: number): string | null {
  if (!Number.isFinite(price) || price <= 0) return null;
  const d = Math.max(0, Math.min(8, Math.floor(decimals)));
  const f = 10 ** d;
  const snapped = Math.round(price * f) / f;
  if (!(snapped > 0)) return null;
  return snapped.toFixed(d);
}

function amendable(overlay: ChartOverlay): boolean {
  return (
    overlay.kind === "order" &&
    Boolean(overlay.interactive) &&
    overlay.marketIndex != null &&
    overlay.orderIndex != null &&
    overlay.orderIndex !== ""
  );
}

export function createTicketAmend(
  host: TicketAmendHost,
  opts: { onAmend: (a: TicketAmend) => void }
) {
  let overlays: readonly ChartOverlay[] = [];
  let decimals = 2;
  let captured: {
    overlay: ChartOverlay;
    originTick: string;
    priceTick: string | null;
  } | null = null;
  let locked = new Set<string>();
  let panOff = false;

  function freezePan() {
    if (panOff) return;
    panOff = true;
    host.setPanEnabled(false);
  }

  function restorePan() {
    if (!panOff) return;
    panOff = false;
    host.setPanEnabled(true);
  }

  function previewPrice(): { overlayId: string; price: number } | null {
    if (!captured || captured.priceTick == null) return null;
    const n = Number(captured.priceTick);
    if (!Number.isFinite(n)) return null;
    return { overlayId: captured.overlay.id, price: n };
  }

  return {
    setOverlays(lines: readonly ChartOverlay[]) {
      overlays = lines;
      locked.clear();
    },
    setPriceDecimals(n: number) {
      decimals = n;
    },
    pointerDown(pt: { x: number; y: number }): boolean {
      if (captured) return false;
      const hit = host.hit(pt);
      if (!hit || hit.region !== "body") return false;
      const live = overlays.find((l) => l.id === hit.overlay.id) ?? hit.overlay;
      if (!amendable(live) || locked.has(live.id)) return false;
      const fromY = snapTick(host.priceAtY(pt.y) ?? live.price, decimals);
      const originTick = snapTick(live.price, decimals);
      if (originTick == null) return false;
      captured = {
        overlay: live,
        originTick,
        priceTick: fromY,
      };
      freezePan();
      return true;
    },
    pointerMove(pt: { x: number; y: number }) {
      if (!captured) return;
      const raw = host.priceAtY(pt.y);
      if (raw == null) return;
      captured.priceTick = snapTick(raw, decimals);
    },
    pointerUp() {
      if (!captured) return;
      const drop = captured;
      captured = null;
      restorePan();
      if (drop.priceTick == null || drop.priceTick === drop.originTick) return;
      if (drop.overlay.marketIndex == null || drop.overlay.orderIndex == null) return;
      locked.add(drop.overlay.id);
      opts.onAmend({
        overlayId: drop.overlay.id,
        marketIndex: drop.overlay.marketIndex,
        orderIndex: drop.overlay.orderIndex,
        price: drop.priceTick,
      });
    },
    pointerCancel() {
      if (!captured) return;
      captured = null;
      restorePan();
    },
    preview() {
      return previewPrice();
    },
    destroy() {
      captured = null;
      restorePan();
    },
  };
}
