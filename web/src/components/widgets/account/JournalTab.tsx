import { useCallback, useEffect, useMemo, useState } from "react";
import { JournalChart } from "@/components/widgets/account/JournalChart";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  api,
  type JournalSummaryGroup,
  type JournalTrip,
} from "@/lib/api";
import { notifyErr } from "@/lib/notify";
import { formatSigned } from "@/lib/utils";

const RANGES = ["7d", "30d", "90d", "all"] as const;
const ALGOS = ["", "planner", "chase", "grid", "ladder", "twap", "trail", "manual"] as const;
const RANGE_DAYS: Record<(typeof RANGES)[number], number | null> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  all: null,
};

function seconds(ts: number): number {
  return ts > 1e12 ? ts / 1000 : ts;
}

function when(ts: number): string {
  return new Date(seconds(ts) * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function heldFor(open: number, close: number | null): string {
  const end = close == null ? Date.now() / 1000 : seconds(close);
  const sec = Math.max(0, Math.round(end - seconds(open)));
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))}m`;
  if (sec < 86_400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86_400)}d`;
}

function money(value: string | null | undefined): string {
  return formatSigned(value, 2);
}

function magnitude(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(fraction: string | null | undefined): string {
  if (fraction == null) return "—";
  return `${(Number(fraction) * 100).toFixed(0)}%`;
}

function pnlClass(value: string | null | undefined): string {
  const n = Number(value ?? "0");
  if (n > 0) return "text-bid";
  if (n < 0) return "text-ask";
  return "text-muted-foreground";
}

function inRange(trip: JournalTrip, range: (typeof RANGES)[number]): boolean {
  if (trip.open) return true;
  const days = RANGE_DAYS[range];
  if (days == null || trip.close_ts == null) return days == null;
  return seconds(trip.close_ts) >= Date.now() / 1000 - days * 86_400;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono tabular-nums ${tone ?? ""}`}>{value}</span>
    </div>
  );
}

export function JournalTab({ active }: { active: boolean }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("30d");
  const [market, setMarket] = useState("");
  const [algo, setAlgo] = useState("");
  const [trips, setTrips] = useState<JournalTrip[]>([]);
  const [strip, setStrip] = useState<JournalSummaryGroup | null>(null);
  const [days, setDays] = useState<JournalSummaryGroup[]>([]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const filter = { market: market || undefined, algo: algo || undefined };
      const [tripPage, none, byDay] = await Promise.all([
        api.journalTrips({ ...filter, limit: 200 }),
        api.journalSummary({ range, group: "none", ...filter }),
        api.journalSummary({ range, group: "day", ...filter }),
      ]);
      setTrips(tripPage.trips);
      setStrip(none.groups[0] ?? null);
      setDays(byDay.groups);
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Failed to load the journal");
    } finally {
      setLoading(false);
    }
  }, [algo, market, range]);

  useEffect(() => {
    if (!active) return;
    void load();
  }, [active, load]);

  const shown = useMemo(
    () => trips.filter((trip) => inRange(trip, range)),
    [range, trips],
  );
  const bars = useMemo(
    () =>
      [...days]
        .sort((a, b) => a.key.localeCompare(b.key))
        .map((day) => ({
          time: Math.floor(Date.parse(`${day.key}T00:00:00Z`) / 1000),
          net: Number(day.net ?? "0"),
        })),
    [days],
  );

  const saveNote = async (trip: JournalTrip, note: string) => {
    if (note === trip.note) return;
    try {
      await api.journalNote(trip.trip_key, { note, tags: trip.tags });
      setTrips((prev) => prev.map((row) => (row.trip_key === trip.trip_key ? { ...row, note } : row)));
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Failed to save the note");
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 text-base">
      <div className="flex flex-wrap items-center gap-2 px-2 pt-2">
        <ToggleGroup
          type="single"
          size="sm"
          value={range}
          onValueChange={(value) => {
            if (value) setRange(value as (typeof RANGES)[number]);
          }}
        >
          {RANGES.map((item) => (
            <ToggleGroupItem key={item} value={item} className="h-6 px-2 text-xs">
              {item === "all" ? "All" : item}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <input
          aria-label="Market"
          value={market}
          placeholder="Market"
          onChange={(e) => setMarket(e.target.value.trim())}
          className="h-6 w-20 rounded border border-border bg-transparent px-1.5 font-mono uppercase"
        />
        <select
          aria-label="Algo"
          value={algo}
          onChange={(e) => setAlgo(e.target.value)}
          className="h-6 rounded border border-border bg-transparent px-1"
        >
          {ALGOS.map((item) => (
            <option key={item || "all"} value={item}>
              {item || "All algos"}
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-4 gap-2 px-2 sm:grid-cols-8">
        <Stat label="Net" value={money(strip?.net)} tone={pnlClass(strip?.net)} />
        <Stat label="Fees" value={magnitude(strip?.fees)} />
        <Stat label="Funding" value={money(strip?.funding)} tone={pnlClass(strip?.funding)} />
        <Stat label="Win %" value={pct(strip?.win_rate)} />
        <Stat label="Profit factor" value={strip?.profit_factor ?? "—"} />
        <Stat label="Expectancy" value={money(strip?.expectancy)} tone={pnlClass(strip?.expectancy)} />
        <Stat label="Avg R" value={strip?.avg_r ?? "—"} />
        <Stat
          label="Max drawdown"
          value={magnitude(strip?.max_drawdown)}
          tone={Number(strip?.max_drawdown ?? "0") > 0 ? "text-ask" : undefined}
        />
      </div>
      {bars.length > 0 ? <JournalChart days={bars} /> : null}
      <ScrollArea className="min-h-0 flex-1">
        {shown.length === 0 && !loading ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No round trips</EmptyTitle>
              <EmptyDescription>Closed trips in this range show up here.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
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
              {shown.map((trip) => (
                <TripRows
                  key={trip.trip_key}
                  trip={trip}
                  open={openKey === trip.trip_key}
                  onToggle={() => setOpenKey((key) => (key === trip.trip_key ? null : trip.trip_key))}
                  onNote={(note) => void saveNote(trip, note)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </ScrollArea>
    </div>
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
        className={trip.partial ? "opacity-60" : undefined}
        title={trip.partial_reason ?? undefined}
        onClick={onToggle}
      >
        <TableCell className="font-mono">{trip.symbol}</TableCell>
        <TableCell className={trip.side === "long" ? "text-bid" : "text-ask"}>
          {trip.open ? `${trip.side} · open` : trip.side}
        </TableCell>
        <TableCell className="font-mono">{when(trip.open_ts)}</TableCell>
        <TableCell className="font-mono">{heldFor(trip.open_ts, trip.close_ts)}</TableCell>
        <TableCell className="text-right font-mono">{trip.size ?? "—"}</TableCell>
        <TableCell className="text-right font-mono">
          {trip.avg_in ?? "—"}
          {trip.avg_out ? ` → ${trip.avg_out}` : ""}
        </TableCell>
        <TableCell className={`text-right font-mono ${pnlClass(net)}`}>{money(net)}</TableCell>
        <TableCell className="text-right font-mono">{trip.r ?? "—"}</TableCell>
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
              <TableCell className="font-mono">{when(fill.ts)}</TableCell>
              <TableCell>{fill.is_maker ? "maker" : "taker"}</TableCell>
              <TableCell className="text-right font-mono">{fill.size}</TableCell>
              <TableCell className="text-right font-mono">{fill.price}</TableCell>
              <TableCell className={`text-right font-mono ${pnlClass(fill.pnl)}`}>{money(fill.pnl)}</TableCell>
              <TableCell className="text-right font-mono">{money(fill.fee)}</TableCell>
              <TableCell colSpan={2} />
            </TableRow>
          ))
        : null}
    </>
  );
}
