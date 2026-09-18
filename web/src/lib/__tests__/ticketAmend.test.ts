import { describe, expect, it } from "vitest";
import type { ChartOverlay } from "@/lib/chartTradingLines";
import {
  createTicketAmend,
  type TicketAmend,
  type TicketAmendHost,
} from "@/lib/ticketAmend";

function ticket(partial?: Partial<ChartOverlay>): ChartOverlay {
  return {
    id: "ord-1",
    kind: "order",
    price: 100,
    color: "#3dd68c",
    label: "BUY 0.5",
    marketIndex: 1,
    orderIndex: "42",
    interactive: true,
    ...partial,
  };
}

function harness(opts?: {
  hit?: TicketAmendHost["hit"];
  prices?: Record<number, number | null>;
}) {
  const amends: TicketAmend[] = [];
  const pan: boolean[] = [];
  const prices = opts?.prices ?? {};
  const host: TicketAmendHost = {
    priceAtY(y) {
      return y in prices ? prices[y]! : null;
    },
    setPanEnabled(enabled) {
      pan.push(enabled);
    },
    hit: opts?.hit ?? (() => null),
  };
  const session = createTicketAmend(host, { onAmend: (a) => amends.push(a) });
  return { session, amends, pan, host };
}

describe("createTicketAmend", () => {
  it("emits one tick-snapped Amend when a Ticket body is dragged to a new price", () => {
    const overlay = ticket();
    const { session, amends } = harness({
      hit: () => ({ overlay, region: "body" }),
      prices: { 80: 100, 20: 101.234 },
    });
    session.setPriceDecimals(2);
    session.setOverlays([overlay]);

    expect(session.pointerDown({ x: 12, y: 80 })).toBe(true);
    session.pointerMove({ x: 12, y: 20 });
    session.pointerUp();

    expect(amends).toEqual([
      { overlayId: "ord-1", marketIndex: 1, orderIndex: "42", price: "101.23" },
    ]);
    expect(session.preview()).toBeNull();
  });

  it("does not Amend a Clip, a cancel hit, or a same-tick drop", () => {
    const clip = ticket({ id: "ord-clip", interactive: false, orderIndex: "9" });
    const live = ticket();
    const { session, amends } = harness({
      hit: (pt) => {
        if (pt.y === 10) return { overlay: clip, region: "body" };
        if (pt.y === 80) return { overlay: live, region: "cancel" };
        if (pt.y === 40) return { overlay: live, region: "body" };
        return null;
      },
      prices: { 10: 99, 80: 100, 40: 100.004, 20: 105 },
    });
    session.setPriceDecimals(2);
    session.setOverlays([clip, live]);

    expect(session.pointerDown({ x: 12, y: 10 })).toBe(false);
    session.pointerMove({ x: 12, y: 20 });
    session.pointerUp();

    expect(session.pointerDown({ x: 12, y: 80 })).toBe(false);
    session.pointerUp();

    expect(session.pointerDown({ x: 12, y: 40 })).toBe(true);
    session.pointerMove({ x: 12, y: 40 });
    session.pointerUp();

    expect(amends).toEqual([]);
  });

  it("Amends when a buy Ticket is dragged through the ask", () => {
    const overlay = ticket({ price: 100, side: "buy" });
    const { session, amends } = harness({
      hit: () => ({ overlay, region: "body" }),
      prices: { 50: 100, 10: 100.8 },
    });
    session.setPriceDecimals(1);
    session.setOverlays([overlay]);

    session.pointerDown({ x: 8, y: 50 });
    session.pointerMove({ x: 8, y: 10 });
    session.pointerUp();

    expect(amends).toEqual([
      { overlayId: "ord-1", marketIndex: 1, orderIndex: "42", price: "100.8" },
    ]);
  });

  it("freezes pan for the drag and restores it on drop, cancel, and destroy", () => {
    const overlay = ticket();
    const { session, pan } = harness({
      hit: () => ({ overlay, region: "body" }),
      prices: { 80: 100, 20: 101 },
    });
    session.setPriceDecimals(0);
    session.setOverlays([overlay]);

    session.pointerDown({ x: 1, y: 80 });
    expect(pan).toEqual([false]);
    expect(session.preview()).toEqual({ overlayId: "ord-1", price: 100 });
    session.pointerMove({ x: 1, y: 20 });
    expect(session.preview()).toEqual({ overlayId: "ord-1", price: 101 });
    session.pointerUp();
    expect(pan).toEqual([false, true]);

    session.setOverlays([overlay]);
    session.pointerDown({ x: 1, y: 80 });
    session.pointerCancel();
    expect(pan).toEqual([false, true, false, true]);

    session.setOverlays([overlay]);
    session.pointerDown({ x: 1, y: 80 });
    session.destroy();
    expect(pan.at(-1)).toBe(true);
    expect(session.preview()).toBeNull();
  });

  it("ignores a second drag of the same Ticket until overlays refresh", () => {
    const overlay = ticket();
    const { session, amends } = harness({
      hit: () => ({ overlay, region: "body" }),
      prices: { 80: 100, 20: 102, 10: 103 },
    });
    session.setPriceDecimals(0);
    session.setOverlays([overlay]);

    session.pointerDown({ x: 1, y: 80 });
    session.pointerMove({ x: 1, y: 20 });
    session.pointerUp();
    expect(amends).toHaveLength(1);

    expect(session.pointerDown({ x: 1, y: 80 })).toBe(false);
    session.pointerMove({ x: 1, y: 10 });
    session.pointerUp();
    expect(amends).toHaveLength(1);

    session.setOverlays([overlay]);
    expect(session.pointerDown({ x: 1, y: 80 })).toBe(true);
    session.pointerMove({ x: 1, y: 10 });
    session.pointerUp();
    expect(amends).toEqual([
      { overlayId: "ord-1", marketIndex: 1, orderIndex: "42", price: "102" },
      { overlayId: "ord-1", marketIndex: 1, orderIndex: "42", price: "103" },
    ]);
  });
});
