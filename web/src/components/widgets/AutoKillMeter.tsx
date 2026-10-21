import type { AutoKillMeter } from "@/lib/autoKillMeter";
import { cn, formatSigned } from "@/lib/utils";

/**
 * Where total uPnL sits between the loss floor and the profit target. Loss fills left of zero
 * in the ask color, profit fills right of it in the bid color. A side without a limit is not drawn.
 */
export function AutoKillMeterBar({
  meter,
  className,
}: {
  meter: AutoKillMeter;
  className?: string;
}) {
  const { lossShare, profitShare } = meter;
  const both = lossShare != null && profitShare != null;
  const share = meter.upnl < 0 ? lossShare : profitShare;
  return (
    <span
      role="meter"
      aria-label={meter.upnl < 0 ? "uPnL toward the loss floor" : "uPnL toward the profit target"}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round((share ?? 0) * 100)}
      aria-valuetext={formatSigned(meter.upnl)}
      className={cn("relative inline-flex h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-border", className)}
    >
      {lossShare != null ? (
        <span
          className="absolute inset-y-0 bg-ask"
          style={{ right: both ? "50%" : undefined, left: both ? undefined : 0, width: `${lossShare * (both ? 50 : 100)}%` }}
        />
      ) : null}
      {profitShare != null ? (
        <span
          className="absolute inset-y-0 bg-bid"
          style={{ left: both ? "50%" : 0, width: `${profitShare * (both ? 50 : 100)}%` }}
        />
      ) : null}
      {both ? <span className="absolute inset-y-0 left-1/2 w-px bg-muted-foreground/60" aria-hidden /> : null}
    </span>
  );
}
