import { ChevronDown, Play } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { algoCanResume, algoIsWorking } from "@/lib/algos";
import type { AlgoState } from "@/lib/api";
import {
  canProtectNow,
  plannerClipLabel,
  plannerPhaseLabel,
  stopLabel,
  plannerTargetsDone,
  rLabel,
  signedPct,
} from "@/lib/plannerPlan";
import { cn, formatSize } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";

/** One Planner: its plan, what is on the venue, and why it waits. */
export function PlannerRow({
  algo,
  busy,
  emphasize,
  tradingEnabled,
  onStop,
  onResume,
  onProtect,
}: {
  algo: AlgoState;
  busy: boolean;
  emphasize?: boolean;
  tradingEnabled: boolean;
  onStop?: () => void;
  onResume?: () => void;
  /** E14: end the entry and put the targets on what filled. */
  onProtect?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const rt = algo.planner;
  const plan = rt?.plan ?? null;
  const long = algo.side === "buy";
  const working = algoIsWorking(algo.status);
  const phase = plannerPhaseLabel(algo);
  const targets = plan?.targets ?? [];
  const done = plannerTargetsDone(algo);
  const live = (algo.clips ?? []).filter((c) => c.status === "live");
  const stop = rt?.stop_trigger ?? plan?.stop ?? null;
  const tone =
    algo.status === "error" ? "ask" : algo.status === "paused" ? "warn" : long ? "bid" : "ask";

  return (
    <div
      className={cn(
        "border-t border-rule px-2 py-2",
        emphasize &&
          (long
            ? "shadow-[inset_2px_0_0_0_var(--color-bid)]"
            : "shadow-[inset_2px_0_0_0_var(--color-ask)]")
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full min-w-0 items-center gap-2 text-left"
      >
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            !expanded && "-rotate-90"
          )}
        />
        <span className={cn("font-mono text-base font-semibold", long ? "text-bid" : "text-ask")}>
          {long ? "LONG" : "SHORT"}
        </span>
        <span className="truncate font-mono text-base font-medium text-text">{algo.symbol ?? "—"}</span>
        <span className="shrink-0 text-xs uppercase tracking-wide text-muted-foreground">Planner</span>
        <Badge variant={tone} className="ml-auto shrink-0">
          {phase}
        </Badge>
      </button>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <div className="min-w-0 font-mono text-sm tabular-nums text-muted-foreground">
          {plan ? (
            <>
              <span className="text-text">{formatSize(rt?.expected_size || plan.size)}</span>
              <span> @ {marketPrice(plan.entry, algo.symbol)}</span>
              <span className="ml-2">R {marketPrice(plan.r, algo.symbol)}</span>
              <span className="ml-2">risk ${Number(parseFloat(plan.risk_usd).toFixed(2))}</span>
              <span className="ml-2">
                TP {done}/{targets.length}
              </span>
            </>
          ) : (
            "—"
          )}
        </div>
        {tradingEnabled && working && (
          <div className="flex shrink-0 items-center gap-0.5">
            {algoCanResume(algo.status) && onResume && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={onResume}
                className="h-6 gap-1 px-1.5"
                title="Accept the Position as it is now and carry on"
              >
                <Play data-icon="inline-start" />
                Resume
              </Button>
            )}
            {onProtect && canProtectNow(algo) && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={onProtect}
                className="h-6 px-1.5"
                title="Ends the entry: what is left comes off, and the targets go on for what filled"
              >
                Protect now
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
                title="Cancels the stop and the targets. The Position is left with no stop."
              >
                Stop
              </Button>
            )}
          </div>
        )}
      </div>

      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-xs text-muted-foreground">
        <span>
          {stopLabel(algo)} <span className="text-ask">{marketPrice(stop, algo.symbol)}</span>
        </span>
        {targets.map((t) => (
          <span key={t.index}>
            TP{t.index} <span className="text-bid">{marketPrice(t.price, algo.symbol)}</span>{" "}
            <span>
              ({signedPct(t.move_pct, 1)}, {rLabel(t.r)})
            </span>
          </span>
        ))}
        {algo.algo_id && <span>{algo.algo_id}</span>}
      </div>

      {(algo.reason || algo.error) && (
        <div
          className={cn(
            "mt-1 truncate font-mono text-sm",
            algo.status === "error" ? "text-ask" : algo.status === "paused" ? "text-warn" : "text-muted-foreground"
          )}
        >
          {algo.error || algo.reason}
        </div>
      )}

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 pt-1">
          <Separator />
          {live.length === 0 && <div className="font-mono text-xs text-muted-foreground">Nothing on the venue</div>}
          {live.map((c) => (
            <div key={c.seq} className="flex items-baseline gap-2 font-mono text-xs">
              <span className={c.side === "buy" ? "text-bid" : "text-ask"}>
                {plannerClipLabel(algo, c.client_order_index) ?? "clip"}
              </span>
              <span className="text-muted-foreground">
                {parseFloat(c.qty) > 0 ? formatSize(c.remaining) : "Position"} @ {marketPrice(c.price, algo.symbol)}
              </span>
            </div>
          ))}
          {(algo.fills ?? []).map((f) => (
            <div key={`f-${f.seq}`} className="flex items-baseline gap-2 font-mono text-xs">
              <span className="text-text">fill</span>
              <span className="text-text">
                {formatSize(f.qty)} @ {marketPrice(f.price, algo.symbol)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
