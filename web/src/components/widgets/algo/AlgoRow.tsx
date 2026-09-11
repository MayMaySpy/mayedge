import { ChevronDown, Pause, Play } from "lucide-react";
import { useState } from "react";
import { notifyOk } from "@/lib/notify";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  algoAvgFillPrice,
  algoCanResume,
  algoFillProgress,
  algoIsWorking,
  algoPhase,
  algoReasonLabel,
} from "@/lib/algos";
import type { AlgoClip, AlgoFill, AlgoState } from "@/lib/api";
import { cn, formatPrice, formatSize } from "@/lib/utils";

function clock(ts: number | null | undefined) {
  if (!ts) return "—";
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function venueRef(row: {
  order_index?: string | number | null;
  client_order_index?: string | number | null;
}) {
  if (row.order_index != null && row.order_index !== "") return String(row.order_index);
  if (row.client_order_index != null) return `coi ${row.client_order_index}`;
  return "—";
}

function copyId(id: string) {
  void navigator.clipboard.writeText(id).then(
    () => notifyOk(`${id} copied`),
    () => {}
  );
}

function statusLine(algo: AlgoState): string | null {
  const phase = algoPhase(algo);
  if (algo.status === "error") {
    return algoReasonLabel(algo.error || algo.reason) || algo.error || "Error";
  }
  if (algo.status === "done") return "Filled";
  if (algo.status === "stopped") return "Stopped";
  if (algo.status === "paused") return "Paused — clips pulled";
  if (phase.key === "active") {
    return `${formatSize(algo.rest_qty)} @ ${formatPrice(algo.rest_price)}`;
  }
  if (phase.key === "wait") {
    return algoReasonLabel(algo.reason) || "Waiting";
  }
  return null;
}

export function AlgoRow({
  algo,
  busy,
  emphasize,
  tradingEnabled,
  defaultExpanded = false,
  onStop,
  onPause,
  onResume,
}: {
  algo: AlgoState;
  busy: boolean;
  emphasize?: boolean;
  tradingEnabled: boolean;
  defaultExpanded?: boolean;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const buy = algo.side === "buy";
  const { filled, remaining, total, pct } = algoFillProgress(algo);
  const avgFill = algoAvgFillPrice(algo.fills);
  const working = algoIsWorking(algo.status);
  const canResume = algoCanResume(algo.status);
  const phase = algoPhase(algo);
  const master = formatSize(total || algo.qty);
  const status = statusLine(algo);
  const fills = [...(algo.fills ?? [])].reverse() as AlgoFill[];
  const live =
    (algo.working as AlgoClip | null | undefined) ??
    algo.clips?.find((c) => c.status === "live") ??
    null;
  const kind =
    algo.algo_type === "chase-iceberg" || algo.id === "chase-iceberg"
      ? "Chase"
      : algo.algo_type === "advanced-twap" || algo.id === "advanced-twap" || algo.id === "twap"
        ? "TWAP"
        : (algo.algo_type ?? algo.id ?? "Algo");

  const badgeVariant =
    phase.tone === "bid"
      ? "bid"
      : phase.tone === "ask"
        ? "ask"
        : phase.tone === "warn"
          ? "warn"
          : "muted";

  return (
    <div
      className={cn(
        "border-t border-rule px-2 py-2",
        emphasize &&
          (buy
            ? "shadow-[inset_2px_0_0_0_var(--color-bid)]"
            : "shadow-[inset_2px_0_0_0_var(--color-ask)]")
      )}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <ChevronDown
            className={cn(
              "size-3.5 shrink-0 text-muted transition-transform",
              !expanded && "-rotate-90"
            )}
          />
          <span className={cn("font-mono text-[12px] font-semibold", buy ? "text-bid" : "text-ask")}>
            {(algo.side ?? "—").toUpperCase()}
          </span>
          <span className="truncate font-mono text-[12px] font-medium text-text">
            {algo.symbol ?? "—"}
          </span>
          <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted">{kind}</span>
          <Badge variant={badgeVariant} className="ml-auto shrink-0">
            {phase.label}
          </Badge>
        </button>
      </div>

      <div className="mt-2 h-1 overflow-hidden rounded-[1px] bg-elevated">
        <div className={cn("h-full", buy ? "bg-bid" : "bg-ask")} style={{ width: `${pct}%` }} />
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div className="min-w-0 font-mono text-[12px] tabular-nums text-text">
          <span>{formatSize(remaining)}</span>
          <span className="text-muted"> / {master}</span>
          <span className="ml-2 text-[10px] text-muted">filled {formatSize(filled)}</span>
          {avgFill != null && (
            <span className="ml-2 text-[10px] text-muted" title="Volume-weighted average fill">
              avg <span className="text-text">{formatPrice(avgFill)}</span>
            </span>
          )}
        </div>
        {tradingEnabled && working && (
          <div className="flex shrink-0 items-center gap-0.5">
            {canResume
              ? onResume && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={onResume}
                    className="h-6 gap-1 px-1.5"
                  >
                    <Play data-icon="inline-start" />
                    Resume
                  </Button>
                )
              : onPause && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={onPause}
                    className="h-6 gap-1 px-1.5"
                  >
                    <Pause data-icon="inline-start" />
                    Pause
                  </Button>
                )}
            {onStop && (
              <Button
                type="button"
                variant="danger"
                size="sm"
                disabled={busy}
                onClick={onStop}
                className="h-6 px-1.5"
              >
                Stop
              </Button>
            )}
          </div>
        )}
      </div>

      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-muted">
        <span>
          Clip <span className="text-text">{formatSize(algo.display_qty)}</span>
        </span>
        <span>
          Off{" "}
          <span className="text-text">
            {algo.offset_bps != null && algo.offset_bps !== "" ? `${algo.offset_bps} bps` : "—"}
          </span>
        </span>
        <span>
          Floor <span className="text-text">{formatPrice(algo.price_floor)}</span>
        </span>
        <span>
          Cap <span className="text-text">{formatPrice(algo.price_ceiling)}</span>
        </span>
        {algo.algo_id && (
          <button
            type="button"
            className="text-muted hover:text-text"
            onClick={() => copyId(algo.algo_id!)}
          >
            {algo.algo_id}
          </button>
        )}
      </div>

      {status && (
        <div
          className={cn(
            "mt-1 truncate font-mono text-[11px]",
            algo.status === "error" ? "text-ask" : phase.tone === "warn" ? "text-warn" : "text-muted"
          )}
        >
          {status}
        </div>
      )}

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 pt-1">
          <Separator />
          {live && (
            <div className="flex items-baseline gap-2 font-mono text-[10px]">
              <span className={buy ? "text-bid" : "text-ask"}>live</span>
              <span className="text-text">{venueRef(live)}</span>
              <span className="text-muted">
                {formatSize(live.remaining)} @ {formatPrice(live.price)}
              </span>
              <span className="ml-auto text-muted">{clock(live.placed_at)}</span>
            </div>
          )}
          {fills.length === 0 && !live && (
            <div className="font-mono text-[10px] text-muted">No clips yet</div>
          )}
          {fills.map((f) => (
            <div key={`f-${f.seq}`} className="flex items-baseline gap-2 font-mono text-[10px]">
              <span className="text-text">fill</span>
              <span className="text-muted">{venueRef(f)}</span>
              <span className="text-text">
                {formatSize(f.qty)} @ {formatPrice(f.price)}
              </span>
              <span className="ml-auto text-muted">{clock(f.ts)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
