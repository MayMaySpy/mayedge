import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { decimalInput, parseDecimal } from "@/lib/numbers";
import {
  trailDistanceLabel,
  trailReferenceLabel,
  trailTriggerAt,
  type TrailExitDraft,
} from "@/lib/trail";
import { cn, formatPrice } from "@/lib/utils";

/** The Trail half of a Stop or Take Profit section in the Position editor. */
export function TrailExitSection({
  kind,
  draft,
  closeSide,
  mark,
  priceDecimals,
  problem,
  replaces,
  partial,
  onChange,
}: {
  kind: "stop" | "tp";
  draft: TrailExitDraft;
  closeSide: "buy" | "sell";
  mark: number;
  priceDecimals: number;
  problem: string | null;
  /** TS4: the Stop Tickets a Trail Stop takes over, as labels. */
  replaces: string[];
  partial: boolean;
  onChange: (draft: TrailExitDraft) => void;
}) {
  const set = (patch: Partial<TrailExitDraft>) => onChange({ ...draft, ...patch });
  const dist = trailDistanceLabel(draft.distance || null, draft.distanceKind);
  const ref = trailReferenceLabel(draft.reference);
  const act = parseDecimal(draft.activation);
  const start = parseDecimal(draft.start);
  const startAt =
    start != null && start > 0 ? start : trailTriggerAt(closeSide, draft, mark, priceDecimals);
  const long = closeSide === "sell";
  const best = long ? "high" : "low";

  let say: string;
  if (kind === "stop") {
    say = `Stop now ${formatPrice(startAt, priceDecimals)}. `;
    say +=
      act != null && act > 0
        ? `From ${formatPrice(act, priceDecimals)} it stays ${dist} behind the best ${ref}.`
        : `It stays ${dist} behind the best ${ref} from now.`;
  } else {
    const at = act != null && act > 0 ? act : NaN;
    const fires = Number.isFinite(at) ? trailTriggerAt(closeSide, draft, at, priceDecimals) : NaN;
    say = Number.isFinite(at)
      ? `At ${formatPrice(at, priceDecimals)} it starts following, and closes ${partial ? "its size" : "the Position"} once ${ref} gives back ${dist} from its ${best} (${formatPrice(fires, priceDecimals)} if that is the ${best}).`
      : `Set the price it starts following from.`;
  }

  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-2 border-t border-rule">
        {kind === "stop" ? (
          <Cell
            label="Starts at"
            value={draft.start}
            placeholder={Number.isFinite(startAt) ? formatPrice(startAt, priceDecimals) : "0.0000"}
            onChange={(start) => set({ start })}
          />
        ) : null}
        <Cell
          label="Activate at"
          value={draft.activation}
          placeholder={kind === "tp" ? "Required" : "Now"}
          onChange={(activation) => set({ activation })}
          className={cn(kind === "stop" && "border-l border-rule", kind === "tp" && "col-span-2")}
        />
      </div>
      <div className="flex items-center gap-2 border-t border-rule bg-elevated/35 px-3 py-2">
        <span className="shrink-0 text-sm text-muted-foreground">Distance</span>
        <input
          aria-label="Distance"
          className="min-w-0 flex-1 bg-transparent text-right font-mono text-base tabular-nums outline-none"
          inputMode="decimal"
          value={draft.distance}
          onChange={(e) => set({ distance: decimalInput(e.target.value) })}
        />
        <ToggleGroup
          type="single"
          variant="seg"
          size="sm"
          spacing={0}
          value={draft.distanceKind}
          onValueChange={(v) => {
            if (v === "pct" || v === "price") set({ distanceKind: v });
          }}
          aria-label="Distance unit"
        >
          <ToggleGroupItem value="pct" className="h-6 px-1.5">
            %
          </ToggleGroupItem>
          <ToggleGroupItem value="price" className="h-6 px-1.5">
            Price
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-rule px-3 py-2">
        <span className="text-sm text-muted-foreground">Follows</span>
        <ToggleGroup
          type="single"
          variant="seg"
          size="sm"
          spacing={0}
          value={draft.reference}
          onValueChange={(v) => {
            if (v === "mark" || v === "last") set({ reference: v });
          }}
          aria-label="Follows"
        >
          <ToggleGroupItem value="mark" className="h-6 px-2">
            Mark
          </ToggleGroupItem>
          <ToggleGroupItem value="last" className="h-6 px-2" title="Every trade print, wicks included">
            Last
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="flex flex-col gap-1 border-t border-rule px-3 py-2 text-sm">
        <p className="text-pretty text-muted-foreground">{say}</p>
        {kind === "stop" && replaces.length > 0 ? (
          <p className="text-warn">Replaces {replaces.join(", ")}.</p>
        ) : null}
        {draft.reference === "last" ? (
          <p className="text-muted-foreground">
            On Last the desk closes on a print, and a venue backstop sits one step behind.
            {partial ? " If both fire, it can close up to twice its size." : ""}
          </p>
        ) : null}
        <p className="text-muted-foreground">
          {kind === "tp"
            ? "Activates only while the desk is running. A fixed Take Profit does not need the desk."
            : "Follows only while the desk is running; while it is down the stop holds where it is."}
        </p>
        {problem ? <p className="text-ask">{problem}</p> : null}
      </div>
    </div>
  );
}

function Cell({
  label,
  value,
  placeholder,
  onChange,
  className,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (raw: string) => void;
  className?: string;
}) {
  return (
    <label
      className={cn(
        "flex min-w-0 items-center gap-2 bg-elevated/35 px-3 py-2.5 focus-within:bg-elevated/60",
        className
      )}
    >
      <span className="shrink-0 text-sm text-muted-foreground">{label}</span>
      <input
        className="min-w-0 flex-1 bg-transparent text-right font-mono text-base tabular-nums outline-none placeholder:text-muted-foreground"
        inputMode="decimal"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(decimalInput(e.target.value))}
      />
    </label>
  );
}
