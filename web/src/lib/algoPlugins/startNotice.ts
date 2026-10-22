import { algoReasonLabel } from "@/lib/algos";
import type { AlgoBook } from "@/lib/api";
import type { OrderNoticeInput } from "@/lib/orderNotice";
import type { AlgoSubmitContext } from "./types";

/**
 * What the ticket says after a desk algo starts: its error, why it waits, or where it
 * rests. `side` is left out for a two-sided algo. `size` is shown until the venue rests one.
 */
export function startNotice(
  book: AlgoBook,
  ctx: AlgoSubmitContext,
  {
    kind,
    label,
    side,
    size,
  }: { kind: "chase" | "grid" | "ladder"; label: string; side?: "buy" | "sell"; size: string }
): { book: AlgoBook; setLiveBook: true; notice: OrderNoticeInput } {
  const just = book.working?.[0];
  const symbol = ctx.market.symbol;
  if (just?.status === "error") {
    return {
      book,
      setLiveBook: true,
      notice: { kind, status: "error", note: just.error || `${label} error`, symbol },
    };
  }
  if (just?.quote_action === "pause") {
    return {
      book,
      setLiveBook: true,
      notice: {
        kind,
        side,
        size: just.rest_qty ?? size,
        symbol,
        status: "paused",
        note: algoReasonLabel(just.reason) || "waiting",
      },
    };
  }
  return {
    book,
    setLiveBook: true,
    notice: {
      kind,
      side,
      size: just?.rest_qty ?? size,
      symbol,
      price: just?.rest_price ?? undefined,
      status: "active",
    },
  };
}
