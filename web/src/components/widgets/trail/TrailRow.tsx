import { ChevronDown, Play } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { algoCanResume, algoIsWorking } from "@/lib/algos";
import type { AlgoState } from "@/lib/api";
import {
  TRAIL_KIND_LABEL,
  trailDistanceLabel,
  trailPhase,
  trailReferenceLabel,
} from "@/lib/trail";
import { cn, formatPrice, formatSize } from "@/lib/utils";

function agoLabel(ms: number | null | undefined): string | null {
  if (!ms) return null;
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m}m ago` : `${Math.round(m / 60)}h ago`;
}

/** One Trail: what it follows, where its trigger is, and why it waits (trail-rules.md). */
export function TrailRow({
  algo,
  busy,
  emphasize,
  tradingEnabled,
  onStop,
  onResume,
}: {
  algo: AlgoState;
  busy: boolean;
  emphasize?: boolean;
  tradingEnabled: boolean;
  /** keepStop: a Trail Stop leaves a plain Stop Ticket at its trigger (S5). */
  onStop?: (keepStop: boolean) => void;
  onResume?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const rt = algo.trail;
  const kind = rt?.kind ?? "stop";
  const phase = trailPhase(algo);
  const working = algoIsWorking(algo.status);
  // A Trail's side is the side it fires. An exit that sells closes a long.
  const sells = rt?.side === "sell";
  // A long is bought in, and closed by a sell.
  const long = kind === "entry" ? !sells : sells;
  const tone =
    phase === "error"
      ? "ask"
      : phase === "paused" || phase === "not following"
        ? "warn"
        : phase === "waiting"
          ? "muted"
          : long
            ? "bid"
            : "ask";
  const what =
    kind === "entry"
      ? `${sells ? "SELL" : "BUY"} ${formatSize(rt?.qty ?? algo.qty ?? "")}`
      : kind === "tp"
        ? `${sells ? "LONG" : "SHORT"} ${formatSize(rt?.qty ?? "")}`
        : sells
          ? "LONG"
          : "SHORT";
  const trigger = rt?.trigger ?? rt?.floor ?? null;
  const live = (algo.clips ?? []).filter((c) => c.status === "live");
  const moved = agoLabel(rt?.last_move_ms);

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
        className="flex w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-left"
      >
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            !expanded && "-rotate-90"
          )}
        />
        <span className="shrink-0 text-xs uppercase tracking-wide text-muted-foreground">
          {TRAIL_KIND_LABEL[kind]}
        </span>
        <span className="truncate font-mono text-base font-medium text-text">{algo.symbol ?? "—"}</span>
        <span
          className={cn(
            "font-mono text-sm font-semibold",
            long ? "text-bid" : "text-ask"
          )}
        >
          {what}
        </span>
        <Badge
          variant={tone}
          className="ml-auto shrink-0"
          title={phase === "not following" ? "The market feed is not live; venue orders stay where they are" : undefined}
        >
          {phase}
        </Badge>
      </button>

      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-0.5 font-mono text-sm tabular-nums text-muted-foreground">
          <span className="text-text">
            {trailDistanceLabel(rt?.distance, rt?.distance_kind)} {trailReferenceLabel(rt?.reference)}
          </span>
          {!rt?.active && rt?.activation ? <span>starts at {formatPrice(rt.activation)}</span> : null}
          {trigger ? (
            <span>
              {kind === "entry" ? "fires" : "stop"}{" "}
              <span className={kind === "entry" ? "text-text" : "text-ask"}>{formatPrice(trigger)}</span>
            </span>
          ) : null}
          {rt?.best ? <span>best {formatPrice(rt.best)}</span> : null}
          {rt?.venue_trigger && rt.backstop ? <span>backstop {formatPrice(rt.venue_trigger)}</span> : null}
          {moved && kind !== "entry" ? <span>moved {moved}</span> : null}
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
              >
                <Play data-icon="inline-start" />
                Resume
              </Button>
            )}
            {onStop &&
              (kind === "stop" ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="danger" size="sm" disabled={busy} className="h-6 gap-0.5 px-1.5">
                      Stop
                      <ChevronDown className="size-3" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => onStop(true)}>
                      Keep stop: leave a Stop Ticket at {formatPrice(trigger)}
                    </DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onSelect={() => onStop(false)}>
                      Cancel stop: the Position is left with no stop
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <Button
                  type="button"
                  variant="danger"
                  size="sm"
                  disabled={busy}
                  onClick={() => onStop(false)}
                  className="h-6 px-1.5"
                >
                  Stop
                </Button>
              ))}
          </div>
        )}
      </div>

      {(algo.reason || algo.error) && (
        <div
          className={cn(
            "mt-1 truncate font-mono text-sm",
            algo.status === "error" ? "text-ask" : "text-muted-foreground"
          )}
        >
          {algo.error || algo.reason}
        </div>
      )}

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 border-t border-rule pt-1.5 font-mono text-xs">
          {live.length === 0 && <div className="text-muted-foreground">Nothing on the venue</div>}
          {live.map((c) => (
            <div key={c.seq} className="flex items-baseline gap-2">
              <span className={c.side === "buy" ? "text-bid" : "text-ask"}>
                {rt?.clip_roles?.[String(c.client_order_index)] === "fire"
                  ? "Market"
                  : rt?.backstop
                    ? "Backstop"
                    : "Stop"}
              </span>
              <span className="text-muted-foreground">
                {parseFloat(c.qty) > 0 ? formatSize(c.remaining) : "Position"} @ {formatPrice(c.price)}
              </span>
            </div>
          ))}
          {(algo.fills ?? []).map((f) => (
            <div key={`f-${f.seq}`} className="flex items-baseline gap-2 text-text">
              fill {formatSize(f.qty)} @ {formatPrice(f.price)}
            </div>
          ))}
          <div className="text-muted-foreground">
            {algo.algo_id} · follows only while the desk is running
          </div>
        </div>
      )}
    </div>
  );
}
