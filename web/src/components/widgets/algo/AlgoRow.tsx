import { Pause, Play } from "lucide-react";
import { useState } from "react";
import { notifyOk } from "@/lib/notify";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ClipLine, RowButton, RowFrame, RowNote, RowToggle } from "@/components/widgets/algo/RowParts";
import { algoLabelForType } from "@/lib/algoPlugins";
import {
  algoAvgFillPrice,
  algoCanResume,
  algoCapturedPnl,
  algoFillProgress,
  algoIsWorking,
  algoPhase,
  algoReasonLabel,
} from "@/lib/algos";
import type { AlgoClip, AlgoFill, AlgoState } from "@/lib/api";
import { cn, formatSigned, formatSize, signClass } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";
import { utcClock } from "@/lib/utcTime";

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
    return `${formatSize(algo.rest_qty)} @ ${marketPrice(algo.rest_price, algo.symbol)}`;
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
  const isGrid = algo.algo_type === "chase-grid";
  const twoSided = isGrid;
  const { filled, remaining, total, pct } = algoFillProgress(algo);
  const capturedPnl = algoCapturedPnl(algo);
  const vwap = parseFloat(algo.inventory_vwap ?? "");
  const avgFill = twoSided
    ? (Number.isFinite(vwap) && vwap > 0 ? vwap : null)
    : algoAvgFillPrice(algo.fills);
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
  const liveBid = twoSided
    ? (algo.working_bid ?? null)
    : (algo.working_bid ?? algo.clips?.find((c) => c.side === "buy" && c.status === "live"));
  const liveAsk = twoSided
    ? (algo.working_ask ?? null)
    : (algo.working_ask ?? algo.clips?.find((c) => c.side === "sell" && c.status === "live"));
  const liveTps = isGrid
    ? (algo.clips ?? []).filter((c) => c.status === "live" && c.kind === "tp")
    : [];
  const kind = algoLabelForType(algo.algo_type ?? algo.id);

  const badgeVariant =
    phase.tone === "bid"
      ? "bid"
      : phase.tone === "ask"
        ? "ask"
        : phase.tone === "warn"
          ? "warn"
          : "muted";

  return (
    <RowFrame emphasize={emphasize} long={buy}>
      <div className="flex items-center gap-2">
        <RowToggle
          expanded={expanded}
          onToggle={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span className={cn("font-mono text-base font-semibold", buy ? "text-bid" : "text-ask")}>
            {(algo.side ?? "—").toUpperCase()}
          </span>
          <span className="truncate font-mono text-base font-medium text-text">
            {algo.symbol ?? "—"}
          </span>
          <span className="shrink-0 text-xs uppercase tracking-wide text-muted-foreground">{kind}</span>
          <Badge variant={badgeVariant} className="ml-auto shrink-0">
            {phase.label}
          </Badge>
        </RowToggle>
      </div>

      <div className="mt-2 h-1 overflow-hidden rounded-[1px] bg-elevated">
        <div className={cn("h-full", buy ? "bg-bid" : "bg-ask")} style={{ width: `${pct}%` }} />
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div className="min-w-0 font-mono text-base tabular-nums text-text">
          <span>{formatSize(remaining)}</span>
          <span className="text-muted-foreground"> / {master}</span>
          <span className="ml-2 text-xs text-muted-foreground">filled {formatSize(filled)}</span>
          {avgFill != null && (
            <span className="ml-2 text-xs text-muted-foreground" title="Volume-weighted average fill">
              avg <span className="text-text">{marketPrice(avgFill, algo.symbol)}</span>
            </span>
          )}
          {capturedPnl != null && (
            <span
              className="ml-2 text-xs text-muted-foreground"
              title="Realized from closed lots, before fees"
            >
              pnl <span className={signClass(capturedPnl)}>{formatSigned(capturedPnl)}</span>
            </span>
          )}
        </div>
        {tradingEnabled && working && (
          <div className="flex shrink-0 items-center gap-0.5">
            {canResume
              ? onResume && (
                  <RowButton busy={busy} onClick={onResume} icon={<Play data-icon="inline-start" />}>
                    Resume
                  </RowButton>
                )
              : onPause && (
                  <RowButton busy={busy} onClick={onPause} icon={<Pause data-icon="inline-start" />}>
                    Pause
                  </RowButton>
                )}
            {onStop && (
              <RowButton busy={busy} onClick={onStop} danger>
                Stop
              </RowButton>
            )}
          </div>
        )}
      </div>

      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-xs text-muted-foreground">
        <span>
          Clip <span className="text-text">{formatSize(algo.display_qty)}</span>
        </span>
        {twoSided && (
          <span>
            Inv{" "}
            <span className="text-text">
              {algo.inventory != null && algo.inventory !== "" ? formatSize(algo.inventory) : "0"}
            </span>
          </span>
        )}
        <span>
          Off{" "}
          <span className="text-text">
            {algo.offset_bps != null && algo.offset_bps !== "" ? `${algo.offset_bps} bps` : "—"}
          </span>
        </span>
        {isGrid && (
          <span>
            Profit{" "}
            <span className="text-text">
              {algo.profit_bps != null && algo.profit_bps !== "" ? `${algo.profit_bps} bps` : "—"}
            </span>
          </span>
        )}
        <span>
          Floor <span className="text-text">{marketPrice(algo.price_floor, algo.symbol)}</span>
        </span>
        <span>
          Cap <span className="text-text">{marketPrice(algo.price_ceiling, algo.symbol)}</span>
        </span>
        {algo.algo_id && (
          <button
            type="button"
            className="text-muted-foreground hover:text-text"
            onClick={() => copyId(algo.algo_id!)}
          >
            {algo.algo_id}
          </button>
        )}
      </div>

      <RowNote
        text={status}
        tone={algo.status === "error" ? "error" : phase.tone === "warn" ? "warn" : undefined}
      />

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 pt-1">
          <Separator />
          {isGrid && (algo.lots?.length ?? 0) > 0 && (
            <div className="flex flex-col gap-0.5 font-mono text-xs text-muted-foreground">
              {(algo.lots ?? []).map((lot) => (
                <div key={lot.lot_id} className="flex gap-2">
                  <span className="text-text">tp</span>
                  <span>
                    {formatSize(lot.qty)} @ {marketPrice(lot.tp_price, algo.symbol)}
                    {lot.merged ? " · merged" : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
          {twoSided && liveBid && (
            <ClipLine label="bid" labelClass="text-bid">
              <span className="text-muted-foreground">
                {formatSize(liveBid.remaining)} @ {marketPrice(liveBid.price, algo.symbol)}
              </span>
            </ClipLine>
          )}
          {twoSided && liveAsk && (
            <ClipLine label="ask" labelClass="text-ask">
              <span className="text-muted-foreground">
                {formatSize(liveAsk.remaining)} @ {marketPrice(liveAsk.price, algo.symbol)}
              </span>
            </ClipLine>
          )}
          {liveTps.map((clip) => (
            <ClipLine key={clip.seq} label="profit" labelClass={clip.side === "buy" ? "text-bid" : "text-ask"}>
              <span className="text-muted-foreground">
                {formatSize(clip.remaining)} @ {marketPrice(clip.price, algo.symbol)}
              </span>
            </ClipLine>
          ))}
          {!twoSided && live && (
            <ClipLine label="live" labelClass={buy ? "text-bid" : "text-ask"}>
              <span className="text-text">{venueRef(live)}</span>
              <span className="text-muted-foreground">
                {formatSize(live.remaining)} @ {marketPrice(live.price, algo.symbol)}
              </span>
              <span className="ml-auto text-muted-foreground" title="Placed, UTC">{utcClock(live.placed_at)}</span>
            </ClipLine>
          )}
          {fills.length === 0 && !live && !liveBid && !liveAsk && liveTps.length === 0 && (
            <div className="font-mono text-xs text-muted-foreground">No clips yet</div>
          )}
          {fills.map((f) => (
            <ClipLine key={`f-${f.seq}`} label="fill" labelClass="text-text">
              <span className="text-muted-foreground">{venueRef(f)}</span>
              <span className="text-text">
                {formatSize(f.qty)} @ {marketPrice(f.price, algo.symbol)}
              </span>
              <span className="ml-auto text-muted-foreground" title="Filled, UTC">{utcClock(f.ts)}</span>
            </ClipLine>
          ))}
        </div>
      )}
    </RowFrame>
  );
}
