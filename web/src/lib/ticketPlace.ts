import { snapTick } from "@/lib/ticketAmend";

export type TicketPlace = { side: "buy" | "sell"; price: string };

export type TicketPlaceHost = {
  priceAtY(y: number): number | null;
  regionAt(pt: { x: number; y: number }): "axis" | "pane" | "elsewhere";
};

const DRAG_SLOP = 5;

function dist(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function sideFor(priceTick: string, liveTick: string): "buy" | "sell" | null {
  const px = Number(priceTick);
  const live = Number(liveTick);
  if (!Number.isFinite(px) || !Number.isFinite(live)) return null;
  if (px < live) return "buy";
  if (px > live) return "sell";
  return null;
}

export function createTicketPlace(
  host: TicketPlaceHost,
  opts: { onPlace: (p: TicketPlace) => void }
) {
  let armed = false;
  let decimals = 2;
  let live: number | null = null;
  let down: { pt: { x: number; y: number } } | null = null;
  let dragged = false;

  function intentAt(pt: { x: number; y: number }): TicketPlace | null {
    if (!armed || host.regionAt(pt) !== "axis") return null;
    if (live == null || !(live > 0)) return null;
    const raw = host.priceAtY(pt.y);
    if (raw == null) return null;
    const price = snapTick(raw, decimals);
    const liveTick = snapTick(live, decimals);
    if (price == null || liveTick == null) return null;
    const side = sideFor(price, liveTick);
    if (!side) return null;
    return { side, price };
  }

  return {
    setArmed(next: boolean) {
      armed = next;
      if (!armed) {
        down = null;
        dragged = false;
      }
    },
    setPriceDecimals(n: number) {
      decimals = n;
    },
    setLivePrice(px: number | null) {
      live = px != null && Number.isFinite(px) && px > 0 ? px : null;
    },
    pointerDown(pt: { x: number; y: number }) {
      dragged = false;
      if (!armed || host.regionAt(pt) !== "axis") {
        down = null;
        return;
      }
      down = { pt };
    },
    pointerMove(pt: { x: number; y: number }) {
      if (!down || dragged) return;
      if (dist(down.pt, pt) > DRAG_SLOP) dragged = true;
    },
    pointerUp(pt: { x: number; y: number }) {
      const started = down;
      const wasDrag = dragged;
      down = null;
      dragged = false;
      if (!started || wasDrag) return;
      const place = intentAt(pt);
      if (place) opts.onPlace(place);
    },
    pointerCancel() {
      down = null;
      dragged = false;
    },
    hover(pt: { x: number; y: number }) {
      return intentAt(pt);
    },
    destroy() {
      down = null;
      dragged = false;
    },
  };
}
