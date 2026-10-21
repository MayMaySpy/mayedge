import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { JournalState } from "@/hooks/useJournal";
import { api, type JournalExcursion, type JournalSide, type JournalSummaryGroup, type JournalTrip } from "@/lib/api";
import {
  JOURNAL_ALGOS,
  JOURNAL_RANGES,
  algoLabel,
  bps,
  duration,
  heldFor,
  magnitude,
  money,
  pct,
  pctPoints,
  pnlClass,
  ratio,
  rValue,
  size,
  streak,
  when,
  type JournalRange,
} from "@/lib/journalFormat";
import { marketPrice } from "@/lib/marketFormat";
import { cn, formatUsdCompact } from "@/lib/utils";
import { useEffect, useState, type ReactNode } from "react";

export function JournalControls({ journal, className }: { journal: JournalState; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <ToggleGroup
        type="single"
        size="sm"
        value={journal.range}
        onValueChange={(value) => {
          if (value) journal.setRange(value as JournalRange);
        }}
      >
        {JOURNAL_RANGES.map((item) => (
          <ToggleGroupItem key={item} value={item} className="h-6 px-2 text-xs">
            {item === "all" ? "All" : item}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <input
        aria-label="Market"
        value={journal.market}
        placeholder="Market"
        onChange={(e) => journal.setMarket(e.target.value.trim())}
        className="h-6 w-20 rounded border border-border bg-transparent px-1.5 font-mono uppercase"
      />
      <select
        aria-label="Algo"
        value={journal.algo}
        onChange={(e) => journal.setAlgo(e.target.value)}
        className="h-6 rounded border border-border bg-transparent px-1"
      >
        {JOURNAL_ALGOS.map((item) => (
          <option key={item || "all"} value={item}>
            {algoLabel(item)}
          </option>
        ))}
      </select>
    </div>
  );
}

function Stat({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-muted-foreground">{label}</span>
      <span className="flex min-w-0 items-baseline gap-1.5">
        <span className={cn("shrink-0 font-mono tabular-nums", tone)}>
          {value}
        </span>
        {hint ? <span className="truncate text-xs text-muted-foreground">{hint}</span> : null}
      </span>
    </div>
  );
}

function StatGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-2">
      <h3 className="text-xs uppercase tracking-[0.06em] text-muted-foreground">{title}</h3>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">{children}</div>
    </section>
  );
}

function needs(strip: JournalSummaryGroup | null): string | undefined {
  return strip?.breakeven_win_rate != null ? `needs ${pct(strip.breakeven_win_rate)}` : undefined;
}

function sideStat(label: string, side: JournalSide | null | undefined) {
  return (
    <Stat
      label={label}
      value={side ? money(side.net) : "—"}
      tone={side ? pnlClass(side.net) : undefined}
      hint={side ? `${side.count} · ${pct(side.win_rate)} win` : undefined}
    />
  );
}

/**
 * The headline numbers, from every closed Round trip's Net. The desk tab shows one row;
 * the page (`full`) groups them by what a trader asks: edge, risk, wins, habits.
 */
export function JournalStats({
  strip,
  full = false,
  className,
}: {
  strip: JournalSummaryGroup | null;
  full?: boolean;
  className?: string;
}) {
  const drawdown = Number(strip?.max_drawdown ?? "0");
  const net = <Stat label="Net" value={money(strip?.net)} tone={pnlClass(strip?.net)} />;
  const winRate = <Stat label="Win %" value={pct(strip?.win_rate)} hint={needs(strip)} />;
  const profitFactor = <Stat label="Profit factor" value={ratio(strip?.profit_factor)} />;
  const payoff = <Stat label="Payoff" value={ratio(strip?.payoff_ratio)} hint="avg win ÷ avg loss" />;
  const expectancy = (
    <Stat label="Expectancy" value={money(strip?.expectancy)} tone={pnlClass(strip?.expectancy)} hint="per trip" />
  );
  const maxDrawdown = (
    <Stat label="Max drawdown" value={magnitude(strip?.max_drawdown)} tone={drawdown > 0 ? "text-ask" : undefined} />
  );
  const funding = <Stat label="Funding" value={money(strip?.funding)} tone={pnlClass(strip?.funding)} />;
  const current = <Stat label="Streak" value={streak(strip?.current_streak)} hint="now" />;

  if (!full) {
    return (
      <div className={cn("grid grid-cols-4 gap-x-4 gap-y-2 sm:grid-cols-8", className)}>
        {net}
        {winRate}
        {profitFactor}
        {payoff}
        {expectancy}
        {maxDrawdown}
        {current}
        {funding}
      </div>
    );
  }

  const fees = Number(strip?.fees ?? "0");
  const rCount = strip?.r_count ?? 0;
  return (
    <div className={cn("grid gap-x-8 gap-y-4 lg:grid-cols-2", className)}>
      <StatGroup title="Edge">
        {net}
        <Stat label="Round trips" value={strip ? `${strip.count}` : "—"} hint={strip ? `${strip.wins}W ${strip.losses}L` : undefined} />
        {winRate}
        {profitFactor}
        {payoff}
        {expectancy}
        <Stat
          label="Net per $ traded"
          value={bps(strip?.net_bps)}
          tone={pnlClass(strip?.net_bps)}
          hint={strip?.notional ? `on ${formatUsdCompact(Number(strip.notional))}` : undefined}
        />
        {fees !== 0 ? <Stat label="Fees" value={magnitude(strip?.fees)} /> : funding}
      </StatGroup>
      <StatGroup title="Risk">
        {maxDrawdown}
        <Stat label="Recovery factor" value={ratio(strip?.recovery_factor)} hint="net ÷ drawdown" />
        <Stat label="Avg loss" value={money(strip?.avg_loss)} tone={pnlClass(strip?.avg_loss)} />
        <Stat label="Largest loss" value={money(strip?.largest_loss)} tone={pnlClass(strip?.largest_loss)} />
        <Stat label="Worst day" value={money(strip?.worst_day)} tone={pnlClass(strip?.worst_day)} />
        <Stat label="Longest losing run" value={strip?.max_loss_streak ? `${strip.max_loss_streak}L` : "—"} />
        {fees !== 0 ? funding : null}
      </StatGroup>
      <StatGroup title="Wins">
        <Stat label="Avg win" value={money(strip?.avg_win)} tone={pnlClass(strip?.avg_win)} />
        <Stat label="Largest win" value={money(strip?.largest_win)} tone={pnlClass(strip?.largest_win)} />
        <Stat label="Best day" value={money(strip?.best_day)} tone={pnlClass(strip?.best_day)} />
        <Stat label="Longest winning run" value={strip?.max_win_streak ? `${strip.max_win_streak}W` : "—"} />
        <Stat
          label="Green days"
          value={strip?.trading_days ? `${strip.green_days ?? 0} of ${strip.trading_days}` : "—"}
          hint={strip?.trading_days ? `${Math.round(((strip.green_days ?? 0) / strip.trading_days) * 100)}%` : undefined}
        />
        {current}
      </StatGroup>
      <StatGroup title="Habits">
        <Stat label="Hold, winners" value={duration(strip?.avg_hold_win_s)} hint="avg" />
        <Stat label="Hold, losers" value={duration(strip?.avg_hold_loss_s)} hint="avg" />
        {sideStat("Long", strip?.long)}
        {sideStat("Short", strip?.short)}
        <Stat label="Maker share" value={pct(strip?.maker_share)} hint="of notional" />
        {rCount > 0 ? (
          <Stat
            label="Planner R"
            value={rValue(strip?.avg_r)}
            tone={pnlClass(strip?.avg_r)}
            hint={`avg of ${rCount} of ${strip?.count ?? 0} trips`}
          />
        ) : null}
      </StatGroup>
    </div>
  );
}

function BreakdownRow({ label, row, total = false }: { label: string; row: JournalSummaryGroup; total?: boolean }) {
  return (
    <TableRow className={total ? "border-t border-border font-medium" : undefined}>
      <TableCell>
        <TableName>{label}</TableName>
      </TableCell>
      <TableCell className="text-right">{row.count}</TableCell>
      <TableCell hideBelow="2xs" className="text-right">{pct(row.win_rate)}</TableCell>
      <TableCell hideBelow="2xs" className="text-right">{ratio(row.profit_factor)}</TableCell>
      <TableCell className={cn("text-right", pnlClass(row.net))}>{money(row.net)}</TableCell>
    </TableRow>
  );
}

/** Per market or per algo, from the summary endpoint. `total` is the whole range, as the All row. */
export function JournalBreakdown({
  title,
  column,
  groups,
  total,
}: {
  title: string;
  column: string;
  groups: JournalSummaryGroup[];
  total?: JournalSummaryGroup | null;
}) {
  const rows = [...groups].sort((a, b) => Number(b.net ?? 0) - Number(a.net ?? 0));
  return (
    <section className="flex min-w-0 flex-col gap-1">
      <h2 className="px-2 text-muted-foreground">{title}</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{column}</TableHead>
            <TableHead className="text-right">Trips</TableHead>
            <TableHead hideBelow="2xs" className="text-right">Win %</TableHead>
            <TableHead hideBelow="2xs" className="text-right">PF</TableHead>
            <TableHead className="text-right">Net</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                Nothing closed in this range
              </TableCell>
            </TableRow>
          ) : (
            <>
              {rows.map((row) => (
                <BreakdownRow key={row.key} label={row.key} row={row} />
              ))}
              {total ? <BreakdownRow label="All" row={total} total /> : null}
            </>
          )}
        </TableBody>
      </Table>
    </section>
  );
}

export function JournalTrips({ journal }: { journal: JournalState }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  if (journal.shown.length === 0 && !journal.loading) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>No round trips</EmptyTitle>
          <EmptyDescription>Closed trips in this range show up here.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="pl-2.5">Market</TableHead>
          <TableHead hideBelow="lg">Side</TableHead>
          <TableHead>Opened (UTC)</TableHead>
          <TableHead hideBelow="lg">Held</TableHead>
          <TableHead hideBelow="md" className="text-right">Size</TableHead>
          <TableHead hideBelow="md" className="text-right">Avg</TableHead>
          <TableHead className="text-right">Net</TableHead>
          <TableHead hideBelow="lg" className="text-right">R</TableHead>
          <TableHead hideBelow="3xl">Algo</TableHead>
          <TableHead hideBelow="3xl">Note</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {journal.shown.map((trip) => (
          <TripRows
            key={trip.trip_key}
            trip={trip}
            open={openKey === trip.trip_key}
            onToggle={() => setOpenKey((key) => (key === trip.trip_key ? null : trip.trip_key))}
            onNote={(note) => void journal.saveNote(trip, note)}
          />
        ))}
      </TableBody>
    </Table>
  );
}

/** journal-rules, Excursion: read when a trip is opened; a closed trip's is read once and kept. */
function ExcursionRow({ tripKey }: { tripKey: string }) {
  const [found, setFound] = useState<JournalExcursion | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.journalExcursion(tripKey).then(
      (out) => {
        if (live) setFound(out);
      },
      (e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : "Excursion unavailable");
      },
    );
    return () => {
      live = false;
    };
  }, [tripKey]);
  let body: ReactNode;
  if (error) body = error;
  else if (!found) body = "Reading candles…";
  else if (!found.resolution) body = "No candles cover this trip";
  else
    body = (
      <>
        <span title="Furthest against the average entry">
          MAE <span className={pnlClass(found.mae_usd)}>{pctPoints(found.mae_pct)} ({money(found.mae_usd)})</span>
        </span>
        {" · "}
        <span title="Furthest for the average entry">
          MFE <span className={pnlClass(found.mfe_usd)}>{pctPoints(found.mfe_pct)} ({money(found.mfe_usd)})</span>
        </span>
        <span className="ml-1.5">
          at {found.resolution} bars{found.open ? ", so far" : ""}
        </span>
      </>
    );
  return (
    <TableRow className="text-muted-foreground">
      <TableCell className="pl-2.5" colSpan={10}>
        Excursion: {body}
      </TableCell>
    </TableRow>
  );
}

function TripRows({
  trip,
  open,
  onToggle,
  onNote,
}: {
  trip: JournalTrip;
  open: boolean;
  onToggle: () => void;
  onNote: (note: string) => void;
}) {
  const net = trip.open ? trip.upnl : trip.net;
  return (
    <>
      <TableRow
        accent={trip.side === "long" ? "bid" : "ask"}
        className={cn("cursor-pointer", trip.partial && "opacity-60")}
        title={trip.partial_reason ?? undefined}
        onClick={onToggle}
      >
        <TableCell className="pl-2.5">
          <TableName>{trip.symbol}</TableName>
        </TableCell>
        <TableCell hideBelow="lg" className={trip.side === "long" ? "text-bid" : "text-ask"}>
          {trip.open ? `${trip.side} · open` : trip.side}
        </TableCell>
        <TableCell>{when(trip.open_ts)}</TableCell>
        <TableCell hideBelow="lg">{heldFor(trip.open_ts, trip.close_ts)}</TableCell>
        <TableCell hideBelow="md" className="text-right">{size(trip.size)}</TableCell>
        <TableCell hideBelow="md" className="text-right">
          {marketPrice(trip.avg_in, trip.symbol)}
          {trip.avg_out ? ` → ${marketPrice(trip.avg_out, trip.symbol)}` : ""}
        </TableCell>
        <TableCell className={cn("text-right", pnlClass(net))}>{money(net)}</TableCell>
        <TableCell hideBelow="lg" className={cn("text-right", trip.r ? pnlClass(trip.r) : undefined)}>
          {rValue(trip.r)}
        </TableCell>
        <TableCell hideBelow="3xl">{trip.algo}</TableCell>
        <TableCell hideBelow="3xl" onClick={(e) => e.stopPropagation()}>
          <input
            aria-label={`Note for ${trip.symbol}`}
            defaultValue={trip.note}
            key={trip.note}
            onBlur={(e) => onNote(e.target.value)}
            className="h-6 w-full min-w-24 bg-transparent"
          />
          {trip.partial && trip.partial_reason ? (
            <div className="text-muted-foreground">{trip.partial_reason}</div>
          ) : null}
        </TableCell>
      </TableRow>
      {open ? <ExcursionRow tripKey={trip.trip_key} /> : null}
      {open
        ? trip.fills.map((fill) => (
            <TableRow key={fill.trade_id} className="text-muted-foreground">
              <TableCell className="pl-2.5">{fill.closing ? "close" : "open"}</TableCell>
              <TableCell hideBelow="lg">{fill.side}</TableCell>
              <TableCell>{when(fill.ts)}</TableCell>
              <TableCell hideBelow="lg">{fill.is_maker ? "maker" : "taker"}</TableCell>
              <TableCell hideBelow="md" className="text-right">{size(fill.size)}</TableCell>
              <TableCell hideBelow="md" className="text-right">{marketPrice(fill.price, trip.symbol)}</TableCell>
              <TableCell className={cn("text-right", pnlClass(fill.pnl))}>{money(fill.pnl)}</TableCell>
              <TableCell hideBelow="lg" className="text-right">{money(fill.fee)}</TableCell>
              <TableCell hideBelow="3xl" />
              <TableCell hideBelow="3xl" />
            </TableRow>
          ))
        : null}
    </>
  );
}
