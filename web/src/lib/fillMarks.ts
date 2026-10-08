import { bucketOpen } from "@/lib/openInterest";
import { candleTime } from "@/lib/chartCandles";

export type FillTrade = {
  trade_id: string;
  market_index: number;
  side: string;
  price: string;
  size: string;
  timestamp: number;
};

export type FillMark = {
  time: number;
  side: "buy" | "sell";
  size: number;
  price: number;
  count: number;
};

type Bucket = { size: number; notional: number; count: number };

/** One mark per candle and side. Price is the size-weighted fill. */
export function fillMarks(
  trades: readonly FillTrade[],
  marketIndex: number,
  stepSec: number,
): FillMark[] {
  const seen = new Set<string>();
  const buckets = new Map<string, Bucket>();
  for (const trade of trades) {
    if (trade.market_index !== marketIndex) continue;
    if (trade.side !== "buy" && trade.side !== "sell") continue;
    if (trade.trade_id) {
      if (seen.has(trade.trade_id)) continue;
      seen.add(trade.trade_id);
    }
    const size = Number(trade.size);
    const price = Number(trade.price);
    const sec = candleTime(trade.timestamp) as number;
    if (!(size > 0) || !(price > 0) || !(sec > 0) || !(stepSec > 0)) continue;
    const time = bucketOpen(sec, stepSec);
    const key = `${time}:${trade.side}`;
    const bucket = buckets.get(key) ?? { size: 0, notional: 0, count: 0 };
    bucket.size += size;
    bucket.notional += price * size;
    bucket.count += 1;
    buckets.set(key, bucket);
  }
  const marks: FillMark[] = [];
  for (const [key, bucket] of buckets) {
    const split = key.lastIndexOf(":");
    const side = key.slice(split + 1);
    if (side !== "buy" && side !== "sell") continue;
    marks.push({
      time: Number(key.slice(0, split)),
      side,
      size: bucket.size,
      price: bucket.notional / bucket.size,
      count: bucket.count,
    });
  }
  marks.sort((a, b) => a.time - b.time || (a.side === b.side ? 0 : a.side === "buy" ? -1 : 1));
  return marks;
}
