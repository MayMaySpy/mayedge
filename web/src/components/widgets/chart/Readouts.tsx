import type { LiquidationSummaryHours } from "@/lib/api";
import { formatBarVolume } from "@/lib/chartCandles";
import type { FillMark } from "@/lib/fillMarks";
import { cn, formatApr, formatPct, formatPrice, formatSize, formatUsdCompact } from "@/lib/utils";

import type { Ohlc } from "./chartFormat";

export function OhlcReadout({
  bar,
  decimals,
  showVolume,
  showOi,
  oi,
  showFund,
  fund,
  fills,
}: {
  bar: Ohlc | null;
  decimals: number;
  showVolume?: boolean;
  showOi?: boolean;
  oi?: number | null;
  showFund?: boolean;
  fund?: { apr: number; settled: boolean } | null;
  fills?: FillMark[];
}) {
  if (!bar) {
    return <span className="font-mono text-sm text-muted-foreground">—</span>;
  }
  const up = bar.close >= bar.open;
  const tone = up ? "text-bid" : "text-ask";
  const chg = bar.open !== 0 ? ((bar.close - bar.open) / bar.open) * 100 : null;
  return (
    <span className="flex min-w-0 items-baseline gap-2 overflow-hidden font-mono text-sm tabular-nums">
      <OhlcField k="O" v={bar.open} decimals={decimals} className={tone} />
      <OhlcField k="H" v={bar.high} decimals={decimals} className={tone} />
      <OhlcField k="L" v={bar.low} decimals={decimals} className={tone} />
      <OhlcField k="C" v={bar.close} decimals={decimals} className={tone} />
      {chg != null && <span className={cn("shrink-0", tone)}>{formatPct(chg)}</span>}
      {showVolume ? (
        <span className="inline-flex shrink-0 items-baseline gap-1">
          <span className="text-muted-foreground">V</span>
          <span className="text-muted-foreground">{formatBarVolume(bar.volume ?? 0)}</span>
        </span>
      ) : null}
      {showOi ? (
        <span className="inline-flex shrink-0 items-baseline gap-1">
          <span className="text-muted-foreground">OI</span>
          <span className="text-muted-foreground">{formatUsdCompact(oi) || "—"}</span>
        </span>
      ) : null}
      {showFund ? (
        <span
          className="inline-flex shrink-0 items-baseline gap-1"
          title={fund && !fund.settled ? "Estimate for an hour that has not settled" : undefined}
        >
          <span className="text-muted-foreground">Fund</span>
          <span
            className={
              fund == null || fund.apr === 0
                ? "text-muted-foreground"
                : fund.apr > 0
                  ? "text-ask"
                  : "text-bid"
            }
          >
            {fund ? formatApr(fund.apr) : "—"}
          </span>
          {fund && !fund.settled ? <span className="text-muted-foreground">est</span> : null}
        </span>
      ) : null}
      {fills?.map((mark) => (
        <span
          key={mark.side}
          className={cn("shrink-0", mark.side === "buy" ? "text-bid" : "text-ask")}
        >
          {mark.side === "buy" ? "Buy" : "Sell"} {formatSize(mark.size)} @ {formatPrice(mark.price, decimals)}
          {mark.count > 1 ? ` · ${mark.count}` : ""}
        </span>
      ))}
    </span>
  );
}

function OhlcField({
  k,
  v,
  decimals,
  className,
}: {
  k: string;
  v: number;
  decimals: number;
  className?: string;
}) {
  return (
    <span className="inline-flex shrink-0 items-baseline gap-1">
      <span className="text-muted-foreground">{k}</span>
      <span className={className}>{formatPrice(v, decimals)}</span>
    </span>
  );
}

function liqWindowLabel(hours: LiquidationSummaryHours): string {
  if (hours === 168) return "7d";
  if (hours === 720) return "30d";
  return `${hours}h`;
}

export function LiqsReadout({ hours }: { hours: LiquidationSummaryHours }) {
  return (
    <span className="font-mono text-sm text-muted-foreground tabular-nums">
      {liqWindowLabel(hours)} liqs
    </span>
  );
}

export function NumeraireReadout({ change }: { change: number | null }) {
  if (change == null) {
    return <span className="font-mono text-sm text-muted-foreground">BTC 24h —</span>;
  }
  const tone = change > 0 ? "text-bid" : change < 0 ? "text-ask" : "text-muted-foreground";
  return (
    <span className="flex min-w-0 items-baseline gap-2 overflow-hidden font-mono text-sm tabular-nums">
      <span className="text-muted-foreground">vs BTC</span>
      <span className={cn("shrink-0", tone)}>{formatPct(change)}</span>
    </span>
  );
}
