import { Pause, Play } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ClipLine, RowButton, RowFrame, RowNote, RowToggle } from "@/components/widgets/algo/RowParts";
import { algoCanResume, algoIsWorking, algoPhase, algoReasonLabel } from "@/lib/algos";
import type { AlgoClip, AlgoFill, AlgoState } from "@/lib/api";
import { marketPrice } from "@/lib/marketFormat";
import { massagerRowFacts } from "@/lib/massager";
import { formatSigned, formatSize, signClass } from "@/lib/utils";
import { utcClock } from "@/lib/utcTime";

function statusLine(algo: AlgoState): string | null {
  if (algo.status === "error") return algoReasonLabel(algo.error || algo.reason) || "Error";
  if (algo.status === "stopped") return algoReasonLabel(algo.reason) || "Stopped";
  // MS23: which end of the Band the 1h candle closed past, and at what.
  if (algo.status === "paused" && algo.reason === "left_band") {
    const end = algo.band_side === "below" ? "below" : "above";
    return (
      `Paused — 1h closed ${end} the Band at ${marketPrice(algo.band_close, algo.symbol ?? "")}. ` +
      "Resume, or stop and start at new levels: the Tally carries."
    );
  }
  if (algo.status === "paused") return `Paused — ${algoReasonLabel(algo.reason) || "clips pulled"}`;
  if (algo.reason) return algoReasonLabel(algo.reason);
  return null;
}

/** A Massager in the Algos panel: its Core, Lean, Position range, Captured and Basis (massager-rules). */
export function MassagerRow({
  algo,
  busy,
  emphasize,
  tradingEnabled,
  onStop,
  onPause,
  onResume,
}: {
  algo: AlgoState;
  busy: boolean;
  emphasize?: boolean;
  tradingEnabled: boolean;
  onStop?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const facts = massagerRowFacts(algo);
  const phase = algoPhase(algo);
  const working = algoIsWorking(algo.status);
  const sym = algo.symbol ?? "";
  const live = (algo.clips ?? []).filter((c) => c.status === "live") as AlgoClip[];
  const fills = [...(algo.fills ?? [])].reverse() as AlgoFill[];
  const badge =
    phase.tone === "warn" ? "warn" : phase.tone === "bid" || phase.tone === "ask" ? "bid" : "muted";

  return (
    <RowFrame emphasize={emphasize} long={facts.core >= 0}>
      <RowToggle expanded={expanded} onToggle={() => setExpanded((v) => !v)}>
        <span className="truncate font-mono text-base font-medium text-text">{sym || "—"}</span>
        <span className="shrink-0 text-xs uppercase tracking-wide text-muted-foreground">Massager</span>
        <Badge variant={badge} className="ml-auto shrink-0">
          {phase.label}
        </Badge>
      </RowToggle>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div className="min-w-0 font-mono text-base tabular-nums text-text">
          <span title="Position now">{formatSize(facts.position)}</span>
          <span className="text-muted-foreground">
            {" "}
            in {formatSize(facts.positionLow)} to {formatSize(facts.positionHigh)}
          </span>
          {facts.pnl != null && (
            <span
              className="ml-2 text-xs text-muted-foreground"
              title="Massager P&L: Captured plus the Lean marked at the mid. What this run's own trades made against holding the Core."
            >
              P&L <span className={signClass(facts.pnl)}>{formatSigned(facts.pnl)}</span>
            </span>
          )}
          <span className="ml-2 text-xs text-muted-foreground" title="Realized on the Lean this run, after fees">
            captured{" "}
            <span className={signClass(facts.captured)}>{formatSigned(facts.captured)}</span>
          </span>
          {facts.runs > 1 && (
            <span className="ml-2 text-xs text-muted-foreground" title="Captured over every run on this Position">
              {facts.runs} runs{" "}
              <span className={signClass(facts.tallyCaptured)}>{formatSigned(facts.tallyCaptured)}</span>
            </span>
          )}
        </div>
        {tradingEnabled && working && (
          <div className="flex shrink-0 items-center gap-0.5">
            {algoCanResume(algo.status)
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
          Core <span className="text-text">{formatSize(facts.core)}</span>
        </span>
        <span>
          Lean <span className={signClass(facts.lean)}>{formatSigned(facts.lean, 6)}</span>
        </span>
        <span title="What the Position cost per unit after every Massager trade, against the entry its Tally began at. It also falls when the Massager buys below it, so it is not the score: P&L is.">
          Basis <span className="text-text">{marketPrice(algo.basis, sym)}</span>
          {algo.core_entry && <span> vs {marketPrice(algo.core_entry, sym)}</span>}
        </span>
        <span>
          Band{" "}
          <span className="text-text">
            {marketPrice(algo.price_floor, sym)} to {marketPrice(algo.price_ceiling, sym)}
          </span>
        </span>
        <span title={algo.step_mode === "atr" ? "Moves when k × ATR is 20% off" : "Fixed for the run"}>
          Step <span className="text-text">{marketPrice(algo.step, sym)}</span>
          {algo.step_mode === "atr" && (
            <span>
              {" "}
              ({algo.atr_mult}× ATR {algo.atr_tf} {marketPrice(algo.atr, sym)}, moved{" "}
              {utcClock(algo.step_moved_at, false)})
            </span>
          )}
        </span>
        <span>
          Swing <span className="text-text">{formatSize(algo.qty)}</span>
        </span>
        <span>
          Clip <span className="text-text">{formatSize(algo.display_qty)}</span>
        </span>
        <span>
          Level <span className="text-text">{algo.level ?? 0}</span>
        </span>
        {algo.algo_id && <span>{algo.algo_id}</span>}
      </div>

      <RowNote
        text={statusLine(algo)}
        tone={algo.status === "error" ? "error" : phase.tone === "warn" ? "warn" : undefined}
      />

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 pt-1">
          <Separator />
          {live.map((c) => (
            <ClipLine key={c.seq} label={c.kind ?? "clip"} labelClass={c.side === "buy" ? "text-bid" : "text-ask"}>
              <span className="text-muted-foreground">
                {c.side} {formatSize(c.remaining)} @ {marketPrice(c.price, sym)}
              </span>
            </ClipLine>
          ))}
          {live.length === 0 && fills.length === 0 && (
            <div className="font-mono text-xs text-muted-foreground">No clips yet</div>
          )}
          {fills.map((f) => (
            <ClipLine key={`f-${f.seq}`} label="fill" labelClass="text-text">
              <span className="text-text">
                {formatSize(f.qty)} @ {marketPrice(f.price, sym)}
              </span>
              <span className="ml-auto text-muted-foreground" title="Filled, UTC">
                {utcClock(f.ts)}
              </span>
            </ClipLine>
          ))}
        </div>
      )}
    </RowFrame>
  );
}
