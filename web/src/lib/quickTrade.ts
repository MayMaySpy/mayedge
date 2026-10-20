import { api, type Account, type Market } from "@/lib/api";
import { maxOrderSize, trimQty } from "@/components/widgets/orderTicket/math";
import { parseDecimal } from "@/lib/numbers";
import { notifyErr, notifyOrder } from "@/lib/notify";
import { snapTick } from "@/lib/ticketAmend";

export type QuickBbo = { bid?: string | null; ask?: string | null };

export function maxQuickSize(opts: {
  side: "buy" | "sell";
  market: Market;
  account: Account | null;
  bbo: QuickBbo;
}): number {
  const bid = parseFloat(opts.bbo.bid ?? "");
  const ask = parseFloat(opts.bbo.ask ?? "");
  const spot = bid > 0 && ask > 0 ? (bid + ask) / 2 : ask > 0 ? ask : bid;
  const posn = opts.account?.positions.find((p) => p.market_index === opts.market.market_index);
  const signedPos = posn ? parseFloat(posn.size) : 0;
  const lev = posn?.leverage ?? 1;
  const available = parseFloat(opts.account?.trade_available ?? opts.account?.available ?? "0");
  const px = opts.side === "buy" ? (ask > 0 ? ask : spot) : bid > 0 ? bid : spot;
  return maxOrderSize({
    available,
    leverage: lev,
    price: px,
    signedPos,
    side: opts.side,
    reduceOnly: false,
  });
}

export function parseQuickSize(
  qty: string,
  market: Market,
  side: "buy" | "sell",
  account: Account | null,
  bbo: QuickBbo
): { ok: true; size: string } | { ok: false; error: string } {
  const parsed = parseDecimal(qty);
  const decimals = market.size_decimals ?? 4;
  const size = parsed != null ? trimQty(parsed, decimals) : "";
  if (!size) return { ok: false, error: "Set a size" };
  const max = maxQuickSize({ side, market, account, bbo });
  if (max > 0 && parsed != null && parsed > max + 1e-9) {
    return { ok: false, error: `Max ${trimQty(max, decimals)} ${market.symbol}` };
  }
  return { ok: true, size };
}

export function buildQuickLimit(opts: {
  qty: string;
  side: "buy" | "sell";
  price: string;
  market: Market;
  account: Account | null;
  bbo: QuickBbo;
}): { ok: true; size: string; price: string } | { ok: false; error: string } {
  const sized = parseQuickSize(opts.qty, opts.market, opts.side, opts.account, opts.bbo);
  if (!sized.ok) return sized;
  const raw = parseDecimal(opts.price);
  const price = raw != null ? snapTick(raw, opts.market.price_decimals ?? 2) : null;
  if (!price) return { ok: false, error: "Set a size" };
  return { ok: true, size: sized.size, price };
}

let quickBusy = false;

/** The floating Buy/Sell path. Hotkeys call this too, so a repeat cannot send twice. */
export async function submitQuickMarket(opts: {
  market: Market | null;
  tradingEnabled: boolean;
  ready: boolean;
  reason?: string | null;
  qty: string;
  side: "buy" | "sell";
  account: Account | null;
  bbo: QuickBbo;
  slippage: number;
}): Promise<void> {
  if (!opts.market || !opts.tradingEnabled || !opts.ready) {
    if (!opts.ready && opts.reason) notifyErr(opts.reason);
    return;
  }
  const sized = parseQuickSize(opts.qty, opts.market, opts.side, opts.account, opts.bbo);
  if (!sized.ok) {
    notifyErr(sized.error);
    return;
  }
  if (quickBusy) return;
  quickBusy = true;
  try {
    await api.placeMarketOrder({
      market_index: opts.market.market_index,
      side: opts.side,
      size: sized.size,
      slippage: opts.slippage,
      reduce_only: false,
    });
    notifyOrder({ kind: "market", side: opts.side, size: sized.size, symbol: opts.market.symbol });
  } catch (err) {
    notifyErr(err instanceof Error ? err.message : "Order failed");
  } finally {
    quickBusy = false;
  }
}
