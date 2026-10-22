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
import { ClipLine, RowButton, RowFrame, RowNote, RowToggle } from "@/components/widgets/algo/RowParts";
import { algoCanResume, algoIsWorking, algoNoteTone } from "@/lib/algos";
import type { AlgoState } from "@/lib/api";
import {
  TRAIL_KIND_LABEL,
  trailDistanceLabel,
  trailPhase,
  trailReferenceLabel,
} from "@/lib/trail";
import { cn, formatSize } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";

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
    <RowFrame emphasize={emphasize} long={long}>
      <RowToggle
        expanded={expanded}
        onToggle={() => setExpanded((v) => !v)}
        className="flex w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-left"
      >
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
      </RowToggle>

      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-0.5 font-mono text-sm tabular-nums text-muted-foreground">
          <span className="text-text">
            {trailDistanceLabel(rt?.distance, rt?.distance_kind)} {trailReferenceLabel(rt?.reference)}
          </span>
          {!rt?.active && rt?.activation ? <span>starts at {marketPrice(rt.activation, algo.symbol)}</span> : null}
          {trigger ? (
            <span>
              {kind === "entry" ? "fires" : "stop"}{" "}
              <span className={kind === "entry" ? "text-text" : "text-ask"}>{marketPrice(trigger, algo.symbol)}</span>
            </span>
          ) : null}
          {rt?.best ? <span>best {marketPrice(rt.best, algo.symbol)}</span> : null}
          {rt?.venue_trigger && rt.backstop ? <span>backstop {marketPrice(rt.venue_trigger, algo.symbol)}</span> : null}
          {moved && kind !== "entry" ? <span>moved {moved}</span> : null}
        </div>
        {tradingEnabled && working && (
          <div className="flex shrink-0 items-center gap-0.5">
            {algoCanResume(algo.status) && onResume && (
              <RowButton busy={busy} onClick={onResume} icon={<Play data-icon="inline-start" />}>
                Resume
              </RowButton>
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
                      Keep stop: leave a Stop Ticket at {marketPrice(trigger, algo.symbol)}
                    </DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onSelect={() => onStop(false)}>
                      Cancel stop: the Position is left with no stop
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <RowButton busy={busy} onClick={() => onStop(false)} danger>
                  Stop
                </RowButton>
              ))}
          </div>
        )}
      </div>

      <RowNote text={algo.error || algo.reason} tone={algoNoteTone(algo.status)} />

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 border-t border-rule pt-1.5 font-mono text-xs">
          {live.length === 0 && <div className="text-muted-foreground">Nothing on the venue</div>}
          {live.map((c) => (
            <ClipLine
              key={c.seq}
              label={
                rt?.clip_roles?.[String(c.client_order_index)] === "fire"
                  ? "Market"
                  : rt?.backstop
                    ? "Backstop"
                    : "Stop"
              }
              labelClass={c.side === "buy" ? "text-bid" : "text-ask"}
            >
              <span className="text-muted-foreground">
                {parseFloat(c.qty) > 0 ? formatSize(c.remaining) : "Position"} @ {marketPrice(c.price, algo.symbol)}
              </span>
            </ClipLine>
          ))}
          {(algo.fills ?? []).map((f) => (
            <div key={`f-${f.seq}`} className="flex items-baseline gap-2 text-text">
              fill {formatSize(f.qty)} @ {marketPrice(f.price, algo.symbol)}
            </div>
          ))}
          <div className="text-muted-foreground">
            {algo.algo_id} · follows only while the desk is running
          </div>
        </div>
      )}
    </RowFrame>
  );
}
