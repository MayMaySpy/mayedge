import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { usePortfolioToday } from "@/hooks/usePortfolioToday";
import type { PortfolioKind, PortfolioKindNow } from "@/lib/api";
import { money, pctPoints, pnlClass } from "@/lib/journalFormat";
import { PORTFOLIO_KIND_LABELS } from "@/lib/portfolioDay";
import { cn } from "@/lib/utils";

const KINDS: PortfolioKind[] = ["perps", "spot", "llp", "staking"];

function held(kind: PortfolioKindNow): boolean {
  return [kind.value, kind.value_at_open, kind.change, kind.flows].some((v) => Number(v ?? "0") !== 0);
}

/** Header: the Portfolio's Day change since local midnight (docs/portfolio-rules.md N9). */
export function PortfolioToday({ enabled }: { enabled: boolean }) {
  const today = usePortfolioToday(enabled);
  if (!today) return null;
  const { total } = today;
  const shown = KINDS.filter((k) => held(today.kinds[k]));
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label="Portfolio today"
          className="inline-flex cursor-default items-baseline gap-1.5 whitespace-nowrap rounded-lg outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <span className="text-xs uppercase tracking-[0.06em] text-muted-foreground">Today</span>
          <span className={cn("font-mono text-lg tabular-nums", pnlClass(total.change))}>{money(total.change)}</span>
          {total.change_pct ? (
            <span className={cn("font-mono text-sm tabular-nums", pnlClass(total.change))}>
              {pctPoints(total.change_pct)}
            </span>
          ) : null}
          {today.mismatch.length > 0 ? (
            <span className="text-sm text-warn" aria-label="Mismatch">
              !
            </span>
          ) : null}
        </button>
      </TooltipTrigger>
      <TooltipContent className="font-mono tabular-nums">
        <div className="grid grid-cols-[auto_auto_auto] gap-x-3 gap-y-0.5">
          <span className="text-muted-foreground">Since local midnight</span>
          <span className="text-right text-muted-foreground">Today</span>
          <span className="text-right text-muted-foreground">Value</span>
          {shown.map((k) => (
            <PortfolioRow key={k} label={PORTFOLIO_KIND_LABELS[k]} kind={today.kinds[k]} />
          ))}
          <PortfolioRow label="Total" kind={total} strong />
        </div>
        {Number(total.flows ?? "0") !== 0 ? (
          <div className="mt-1 text-muted-foreground">Flows today {money(total.flows)}, not counted as change</div>
        ) : null}
        {today.mismatch.map((m) => (
          <div key={m.kind} className="mt-1 text-warn">
            {PORTFOLIO_KIND_LABELS[m.kind]}: value and PnL disagree by {money(m.drift)}
          </div>
        ))}
      </TooltipContent>
    </Tooltip>
  );
}

function PortfolioRow({ label, kind, strong = false }: { label: string; kind: PortfolioKindNow; strong?: boolean }) {
  return (
    <>
      <span className={strong ? "font-medium" : undefined}>{label}</span>
      <span className={cn("text-right", pnlClass(kind.change))}>{money(kind.change)}</span>
      <span className="text-right">{money(kind.value).replace(/^\+/, "")}</span>
    </>
  );
}
