import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatPrice, formatSize } from "@/lib/utils";
import type { LadderPlan } from "@/lib/ladderPlan";

export function LadderPreviewDialog({
  open,
  onOpenChange,
  plan,
  symbol,
  window,
  priceDecimals,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: LadderPlan;
  symbol: string;
  window: number;
  priceDecimals: number;
}) {
  const liveN = Math.min(Math.max(0, window), plan.orders.length);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[95vh] w-95 max-w-[calc(100vw-16px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-95"
        aria-describedby={undefined}
      >
        <DialogHeader className="flex-row items-center justify-between gap-2 border-b border-rule p-3 pr-10">
          <DialogTitle className="text-sm font-medium text-text">Preview</DialogTitle>
          <DialogDescription className="sr-only">
            Planned ladder orders for {symbol}
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">Average entry</span>
            <span className="font-mono text-xs tabular-nums text-text">
              {formatPrice(plan.avgEntry, priceDecimals)}
            </span>
          </div>
          <div className="border-t border-dashed border-rule" />
          <div className="flex flex-col gap-2">
            <span className="text-sm font-semibold text-text">Quantity allocation</span>
            <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted">
              <span className="w-20">Price</span>
              <span className="flex-1 text-center">Quantity</span>
              <span className="w-16 text-right">Share</span>
            </div>
            <div className="flex max-h-60 flex-col gap-1 overflow-y-auto">
              {plan.orders.map((row, i) => {
                const share = plan.qty > 0 ? (row.qty / plan.qty) * 100 : 0;
                const live = i < liveN;
                return (
                  <div key={`${row.price}-${i}`} className="flex items-center justify-between">
                    <span className="w-20 font-mono text-xs tabular-nums text-muted">
                      {formatPrice(row.price, priceDecimals)}
                    </span>
                    <div className="flex flex-1 items-center justify-center gap-1">
                      <span className="font-mono text-xs font-semibold tabular-nums text-text">
                        {formatSize(row.qty)} {symbol}
                      </span>
                      {live ? (
                        <span className="text-[9px] uppercase tracking-wide text-muted">live</span>
                      ) : null}
                    </div>
                    <span className="w-16 text-right font-mono text-xs tabular-nums text-muted">
                      {share.toFixed(share >= 10 ? 0 : 1)}%
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="text-[10px] text-muted">
              {liveN} of {plan.orders.length} closest rest live; refill on fill.
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
