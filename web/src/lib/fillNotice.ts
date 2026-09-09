import type { AccountTrade } from "@/lib/api";
import type { OrderNoticeInput } from "@/lib/orderNotice";

export function tradeTimestampMs(ts: number): number {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

export function liveFillNotices(
  trades: AccountTrade[],
  opts: { seen: Set<string>; now: number; armedAt: number; maxAgeMs?: number }
): OrderNoticeInput[] {
  const maxAge = opts.maxAgeMs ?? 8_000;
  const out: OrderNoticeInput[] = [];
  for (const t of trades) {
    if (!t.trade_id) continue;
    if (opts.seen.has(t.trade_id)) continue;
    opts.seen.add(t.trade_id);
    const ms = tradeTimestampMs(t.timestamp) || (opts.now - opts.armedAt >= 2_000 ? opts.now : 0);
    if (!ms) continue;
    if (ms < opts.armedAt - 1_000) continue;
    if (opts.now - ms > maxAge) continue;
    out.push({
      kind: "fill",
      status: "filled",
      side: t.side,
      size: t.size,
      symbol: t.symbol,
      price: t.price,
    });
  }
  return out;
}

const seenFills = new Set<string>();
let armedAt = 0;

export function armFillToasts(now = Date.now()) {
  armedAt = now;
}

export function consumeLiveFills(trades: AccountTrade[], now = Date.now()): OrderNoticeInput[] {
  if (!armedAt) return [];
  return liveFillNotices(trades, { seen: seenFills, now, armedAt });
}
