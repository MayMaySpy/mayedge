import { describe, expect, it } from "vitest";
import {
  createTicketPlace,
  type TicketPlace,
  type TicketPlaceHost,
} from "@/lib/ticketPlace";

function harness(opts?: {
  region?: TicketPlaceHost["regionAt"];
  prices?: Record<number, number | null>;
}) {
  const places: TicketPlace[] = [];
  const prices = opts?.prices ?? {};
  const host: TicketPlaceHost = {
    priceAtY(y) {
      return y in prices ? prices[y]! : null;
    },
    regionAt: opts?.region ?? (() => "elsewhere"),
  };
  const session = createTicketPlace(host, { onPlace: (p) => places.push(p) });
  session.setPriceDecimals(2);
  session.setLivePrice(100);
  session.setArmed(true);
  return { session, places };
}

describe("createTicketPlace", () => {
  it("rests a buy Ticket when an armed axis click is below the live price", () => {
    const { session, places } = harness({
      region: () => "axis",
      prices: { 80: 99.444 },
    });
    session.pointerDown({ x: 200, y: 80 });
    session.pointerUp({ x: 200, y: 80 });
    expect(places).toEqual([{ side: "buy", price: "99.44" }]);
  });

  it("rests a sell Ticket when an armed axis click is above the live price", () => {
    const { session, places } = harness({
      region: () => "axis",
      prices: { 20: 100.555 },
    });
    session.pointerDown({ x: 200, y: 20 });
    session.pointerUp({ x: 200, y: 20 });
    expect(places).toEqual([{ side: "sell", price: "100.56" }]);
  });

  it("does not place when unarmed, off the axis, dragged, or on the live tick", () => {
    const { session, places } = harness({
      region: (pt) => (pt.x >= 180 ? "axis" : "pane"),
      prices: { 80: 99, 20: 101, 28: 102, 50: 100, 40: 98 },
    });

    session.setArmed(false);
    session.pointerDown({ x: 200, y: 80 });
    session.pointerUp({ x: 200, y: 80 });

    session.setArmed(true);
    session.pointerDown({ x: 10, y: 80 });
    session.pointerUp({ x: 10, y: 80 });

    session.pointerDown({ x: 200, y: 20 });
    session.pointerMove({ x: 200, y: 28 });
    session.pointerUp({ x: 200, y: 28 });

    session.pointerDown({ x: 200, y: 50 });
    session.pointerUp({ x: 200, y: 50 });

    session.setLivePrice(null);
    session.pointerDown({ x: 200, y: 40 });
    session.pointerUp({ x: 200, y: 40 });

    expect(places).toEqual([]);
  });

  it("previews side and price on an armed axis hover only", () => {
    const { session } = harness({
      region: (pt) => (pt.x >= 180 ? "axis" : "pane"),
      prices: { 80: 99.1, 20: 101.2 },
    });
    expect(session.hover({ x: 200, y: 80 })).toEqual({ side: "buy", price: "99.10" });
    expect(session.hover({ x: 200, y: 20 })).toEqual({ side: "sell", price: "101.20" });
    expect(session.hover({ x: 10, y: 80 })).toBeNull();
    session.setArmed(false);
    expect(session.hover({ x: 200, y: 80 })).toBeNull();
  });
});
