import type { Position } from "@/lib/api";
import { formatSigned } from "@/lib/utils";

function num(raw: string | null | undefined): number {
  const n = parseFloat(raw ?? "");
  return Number.isFinite(n) ? n : 0;
}

/**
 * Total uPnL the way Auto kill measures it (backend `auto_kill.live_upnl`): each Position's
 * (mark − entry) × size, or the venue's uPnL when mark or entry is missing.
 */
export function autoKillUpnl(positions: readonly Position[]): number {
  let total = 0;
  for (const p of positions) {
    const size = num(p.size);
    const entry = num(p.entry_price);
    const mark = num(p.mark_price);
    total += mark > 0 && entry > 0 && size !== 0 ? (mark - entry) * size : num(p.unrealized_pnl);
  }
  return total;
}

export interface AutoKillMeter {
  upnl: number;
  /** 0–1 of the way from 0 to the loss floor. Null without a floor. */
  lossShare: number | null;
  /** 0–1 of the way from 0 to the profit target. Null without a target. */
  profitShare: number | null;
  /** USD left before the floor fires. Null without a floor. */
  toLoss: number | null;
  /** USD left before the target fires. Null without a target. */
  toProfit: number | null;
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

export function autoKillMeter(
  upnl: number,
  lossUsd: number | null | undefined,
  profitUsd: number | null | undefined
): AutoKillMeter {
  const loss = lossUsd != null && lossUsd > 0 ? lossUsd : null;
  const profit = profitUsd != null && profitUsd > 0 ? profitUsd : null;
  return {
    upnl,
    lossShare: loss != null ? clamp01(-upnl / loss) : null,
    profitShare: profit != null ? clamp01(upnl / profit) : null,
    toLoss: loss != null ? Math.max(0, upnl + loss) : null,
    toProfit: profit != null ? Math.max(0, profit - upnl) : null,
  };
}

/** The floor counts as near once uPnL has used this much of it. */
export const AUTO_KILL_NEAR = 0.75;

/** One line per limit: how far uPnL is from it. */
export function autoKillMeterLines(
  meter: AutoKillMeter,
  lossUsd: number | null | undefined,
  profitUsd: number | null | undefined
): string[] {
  const lines = [`uPnL ${formatSigned(meter.upnl)}, as Auto kill measures it: (mark − entry) × size`];
  if (meter.toLoss != null && lossUsd != null) {
    lines.push(
      `Loss floor -${lossUsd}: ${meter.toLoss.toFixed(2)} left (${Math.round((meter.lossShare ?? 0) * 100)}% used)`
    );
  }
  if (meter.toProfit != null && profitUsd != null) {
    lines.push(
      `Profit target +${profitUsd}: ${meter.toProfit.toFixed(2)} to go (${Math.round((meter.profitShare ?? 0) * 100)}%)`
    );
  }
  return lines;
}
