import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableName,
  TableRow,
  type RowAccent,
} from "@/components/ui/table";
import { TokenMark } from "@/components/desk/TokenMark";
import { SortableHeads } from "@/components/widgets/SortableHeads";
import type { Market } from "@/lib/api";
import type { Idea } from "@/lib/api.gen";
import { price } from "@/lib/journalFormat";
import {
  inZone,
  marketLast,
  nextCatalyst,
  pastStop,
  relativeAge,
  rNow,
  toEntryPct,
  type IdeaSort,
} from "@/lib/ideas";
import type { SortCol, TableSort } from "@/lib/tableSort";
import { utcDateTime } from "@/lib/utcTime";
import { cn, formatPct, signClass } from "@/lib/utils";

const COLS: SortCol<IdeaSort>[] = [
  { key: "market", label: "Market", align: "start" },
  { key: null, label: "Side", align: "start" },
  { key: null, label: "Last", align: "end" },
  { key: null, label: "24h", align: "end" },
  { key: "entry", label: "To entry", align: "end" },
  { key: null, label: "R:R", align: "end" },
  { key: "conviction", label: "Conv", align: "end" },
  { key: null, label: "Tags", align: "start" },
  { key: "catalyst", label: "Next", align: "start", hideBelow: "xl" },
  { key: "updated", label: "Upd", align: "end" },
];

const OUTCOME: Record<NonNullable<Idea["outcome"]>, string> = {
  worked: "Worked",
  failed: "Failed",
  missed: "Missed",
  wrong: "Wrong",
};

function accent(idea: Idea, last: number | null): RowAccent | null {
  if (pastStop(idea, last)) return "warn";
  if (inZone(idea, last)) return "bid";
  return null;
}

function formatR(n: number): string {
  const rounded = Math.round(n * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)}R`;
}

function ToEntry({ idea, listed, last }: { idea: Idea; listed: boolean; last: number | null }) {
  if (!listed) return <span className="text-muted-foreground">Not listed</span>;
  if (idea.status === "closed" || idea.status === "dropped") {
    return <span>{idea.outcome ? OUTCOME[idea.outcome] : "—"}</span>;
  }
  if (pastStop(idea, last)) return <span className="text-warn">Past stop</span>;
  const live = rNow(idea, last);
  if (idea.status === "active" && live != null) return <span>{formatR(live)}</span>;
  if (inZone(idea, last)) return <Badge variant="bid">In zone</Badge>;
  const pct = toEntryPct(idea, last);
  if (pct == null) return <span className="text-muted-foreground">—</span>;
  return <span className={signClass(pct)}>{formatPct(pct)}</span>;
}

function Dots({ value }: { value: number }) {
  return (
    <span aria-label={`Conviction ${value}`} className="inline-flex gap-0.5">
      {[1, 2, 3].map((n) => (
        <span
          key={n}
          className={cn("size-1.5 rounded-full", n <= value ? "bg-foreground" : "bg-muted-foreground/30")}
        />
      ))}
    </span>
  );
}

export function IdeaList({
  ideas,
  markets,
  sort,
  onSort,
  selectedId,
  onSelect,
  now,
}: {
  ideas: Idea[];
  markets: ReadonlyMap<string, Market>;
  sort: IdeaSort;
  onSort: (key: IdeaSort) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  now: number;
}) {
  const tableSort: TableSort<IdeaSort> = { key: sort, dir: sort === "market" ? "asc" : "desc" };
  return (
    <div className="min-h-0 overflow-y-auto rounded-lg border border-rule bg-panel">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-panel">
          <tr>
            <SortableHeads cols={COLS} sort={tableSort} onSort={onSort} />
          </tr>
        </TableHeader>
        <TableBody>
          {ideas.map((idea) => {
            const market = markets.get(idea.symbol);
            const last = marketLast(market);
            const catalyst = nextCatalyst(idea, now);
            const multiples = idea.r_multiples ?? [];
            const lastR = multiples.length ? Number(multiples[multiples.length - 1]) : null;
            return (
              <TableRow
                key={idea.id}
                accent={accent(idea, last)}
                data-state={idea.id === selectedId ? "selected" : undefined}
                className="cursor-pointer"
                onClick={() => onSelect(idea.id)}
              >
                <TableCell>
                  <span className="inline-flex items-center gap-1.5">
                    <TokenMark symbol={idea.symbol} className="size-4" />
                    <TableName>{idea.symbol}</TableName>
                  </span>
                </TableCell>
                <TableCell>
                  <Badge variant={idea.side === "long" ? "bid" : "ask"}>{idea.side === "long" ? "L" : "S"}</Badge>
                </TableCell>
                <TableCell className="text-right">{last == null ? "—" : price(String(last))}</TableCell>
                <TableCell className={cn("text-right", signClass(market?.change_24h))}>
                  {market ? formatPct(market.change_24h) : "—"}
                </TableCell>
                <TableCell className="text-right">
                  <ToEntry idea={idea} listed={market != null} last={last} />
                </TableCell>
                <TableCell
                  className="text-right"
                  title={multiples.map((r, i) => `T${i + 1} ${r}R`).join(" · ") || undefined}
                >
                  {lastR == null || !Number.isFinite(lastR) ? "—" : lastR.toFixed(1)}
                </TableCell>
                <TableCell className="text-right">
                  <Dots value={idea.conviction} />
                </TableCell>
                <TableCell>
                  <span className="inline-flex gap-1 font-sans">
                    {idea.tags.slice(0, 2).map((tag) => (
                      <Badge key={tag} variant="muted">
                        {tag}
                      </Badge>
                    ))}
                    {idea.tags.length > 2 ? <span className="text-muted-foreground">+{idea.tags.length - 2}</span> : null}
                  </span>
                </TableCell>
                <TableCell
                  hideBelow="xl"
                  title={
                    catalyst
                      ? `${catalyst.text} · ${catalyst.time ? `${catalyst.date} ${catalyst.time}` : catalyst.date} UTC`
                      : undefined
                  }
                >
                  {catalyst ? (catalyst.days === 0 ? "today" : `in ${catalyst.days}d`) : "—"}
                </TableCell>
                <TableCell className="text-right" title={`${utcDateTime(idea.updated_at)} UTC`}>
                  {relativeAge(idea.updated_at, now)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
