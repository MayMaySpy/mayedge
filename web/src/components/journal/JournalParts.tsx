import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { JournalState } from "@/hooks/useJournal";
import type { JournalSummaryGroup, JournalTrip } from "@/lib/api";
import {
  JOURNAL_ALGOS,
  JOURNAL_RANGES,
  heldFor,
  magnitude,
  money,
  pct,
  pnlClass,
  price,
  ratio,
  rValue,
  size,
  when,
  type JournalRange,
} from "@/lib/journalFormat";
import { cn } from "@/lib/utils";
import { useState } from "react";

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
            {item || "All algos"}
          </option>
        ))}
      </select>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-muted-foreground">{label}</span>
      <span className={cn("truncate font-mono tabular-nums", tone)} title={value}>
        {value}
      </span>
    </div>
  );
}

/** The headline numbers. `full` adds the second row the page has room for. */
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
  return (
    <div
      className={cn(
        "grid gap-x-4 gap-y-2",
        full ? "grid-cols-2 sm:grid-cols-4 lg:grid-cols-8" : "grid-cols-4 sm:grid-cols-8",
        className,
      )}
    >
      <Stat label="Net" value={money(strip?.net)} tone={pnlClass(strip?.net)} />
      <Stat label="Fees" value={magnitude(strip?.fees)} />
      <Stat label="Funding" value={money(strip?.funding)} tone={pnlClass(strip?.funding)} />
      <Stat label="Win %" value={pct(strip?.win_rate)} />
      <Stat label="Profit factor" value={ratio(strip?.profit_factor)} />
      <Stat label="Expectancy" value={money(strip?.expectancy)} tone={pnlClass(strip?.expectancy)} />
      <Stat label="Avg R" value={rValue(strip?.avg_r)} tone={pnlClass(strip?.avg_r)} />
      <Stat label="Max drawdown" value={magnitude(strip?.max_drawdown)} tone={drawdown > 0 ? "text-ask" : undefined} />
      {full ? (
        <>
          <Stat label="Round trips" value={strip ? `${strip.count} · ${strip.wins}W ${strip.losses}L` : "—"} />
          <Stat label="Gross" value={money(strip?.gross_pnl)} tone={pnlClass(strip?.gross_pnl)} />
          <Stat label="Avg win" value={money(strip?.avg_win)} tone={pnlClass(strip?.avg_win)} />
          <Stat label="Avg loss" value={money(strip?.avg_loss)} tone={pnlClass(strip?.avg_loss)} />
          <Stat label="Largest win" value={money(strip?.largest_win)} tone={pnlClass(strip?.largest_win)} />
          <Stat label="Largest loss" value={money(strip?.largest_loss)} tone={pnlClass(strip?.largest_loss)} />
          <Stat label="Maker share" value={pct(strip?.maker_share)} />
          <Stat label="Total R" value={rValue(strip?.total_r)} tone={pnlClass(strip?.total_r)} />
        </>
      ) : null}
    </div>
  );
}

/** Per market or per algo, from the summary endpoint. */
export function JournalBreakdown({
  title,
  column,
  groups,
}: {
  title: string;
  column: string;
  groups: JournalSummaryGroup[];
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
            <TableHead className="text-right">Win %</TableHead>
            <TableHead className="text-right">PF</TableHead>
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
            rows.map((row) => (
              <TableRow key={row.key}>
                <TableCell className="font-mono">{row.key}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{row.count}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{pct(row.win_rate)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{ratio(row.profit_factor)}</TableCell>
                <TableCell className={cn("text-right font-mono tabular-nums", pnlClass(row.net))}>
                  {money(row.net)}
                </TableCell>
              </TableRow>
            ))
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
          <TableHead>Market</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Opened</TableHead>
          <TableHead>Held</TableHead>
          <TableHead className="text-right">Size</TableHead>
          <TableHead className="text-right">Avg</TableHead>
          <TableHead className="text-right">Net</TableHead>
          <TableHead className="text-right">R</TableHead>
          <TableHead>Algo</TableHead>
          <TableHead>Note</TableHead>
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
        className={cn("cursor-pointer", trip.partial && "opacity-60")}
        title={trip.partial_reason ?? undefined}
        onClick={onToggle}
      >
        <TableCell className="font-mono">{trip.symbol}</TableCell>
        <TableCell className={trip.side === "long" ? "text-bid" : "text-ask"}>
          {trip.open ? `${trip.side} · open` : trip.side}
        </TableCell>
        <TableCell className="whitespace-nowrap font-mono">{when(trip.open_ts)}</TableCell>
        <TableCell className="font-mono">{heldFor(trip.open_ts, trip.close_ts)}</TableCell>
        <TableCell className="text-right font-mono tabular-nums">{size(trip.size)}</TableCell>
        <TableCell className="whitespace-nowrap text-right font-mono tabular-nums">
          {price(trip.avg_in)}
          {trip.avg_out ? ` → ${price(trip.avg_out)}` : ""}
        </TableCell>
        <TableCell className={cn("text-right font-mono tabular-nums", pnlClass(net))}>{money(net)}</TableCell>
        <TableCell className={cn("text-right font-mono tabular-nums", trip.r ? pnlClass(trip.r) : undefined)}>
          {rValue(trip.r)}
        </TableCell>
        <TableCell>{trip.algo}</TableCell>
        <TableCell onClick={(e) => e.stopPropagation()}>
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
      {open
        ? trip.fills.map((fill) => (
            <TableRow key={fill.trade_id} className="text-muted-foreground">
              <TableCell className="font-mono">{fill.closing ? "close" : "open"}</TableCell>
              <TableCell>{fill.side}</TableCell>
              <TableCell className="whitespace-nowrap font-mono">{when(fill.ts)}</TableCell>
              <TableCell>{fill.is_maker ? "maker" : "taker"}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{size(fill.size)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{price(fill.price)}</TableCell>
              <TableCell className={cn("text-right font-mono tabular-nums", pnlClass(fill.pnl))}>
                {money(fill.pnl)}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">{money(fill.fee)}</TableCell>
              <TableCell colSpan={2} />
            </TableRow>
          ))
        : null}
    </>
  );
}
