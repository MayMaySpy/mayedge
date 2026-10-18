import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellOff, X } from "lucide-react";
import { notifyDesk } from "@/lib/notify";
import { FilterPopover } from "@/components/desk/FilterPopover";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, type AlertStats, type FundingExtremeRow } from "@/lib/api";
import {
  directionArrow,
  directionClass,
  eventLine,
  eventMs,
  formatClock,
  ruleName,
  severityBorder,
  shownAlerts,
  toastCopy,
  type AlertLine,
} from "@/lib/alertFormat";
import { useFavorites } from "@/lib/favorites";
import { useFundingExtremes, useLiveAlerts } from "@/lib/liveData";
import { formatFundingPct } from "@/lib/marketPicker";
import { pairLabel } from "@/lib/venuePair";
import { cn } from "@/lib/utils";

const MIN_SEV_KEY = "mayedge-alerts-min-sev";
const FAV_ONLY_KEY = "mayedge-alerts-fav-only";
const MUTE_KEY = "mayedge-alerts-muted";
const NOTABLE = 2;
const URGENT = 3;
const MAX_ROWS = 80;
const TOAST_MAX = 2;
const TOAST_MAX_AGE_MS = 8_000;
const STRIP_MAX = 8;

const SEV_CHOICES = [
  { value: NOTABLE, label: "All" },
  { value: URGENT, label: "Urgent" },
] as const;

function loadMinSev(): number {
  try {
    return parseInt(localStorage.getItem(MIN_SEV_KEY) ?? "", 10) >= URGENT ? URGENT : NOTABLE;
  } catch {
    return NOTABLE;
  }
}

function loadFavOnly(): boolean {
  try {
    return localStorage.getItem(FAV_ONLY_KEY) === "1";
  } catch {
    return false;
  }
}

function loadMuted(): Set<string> {
  try {
    const parsed = JSON.parse(localStorage.getItem(MUTE_KEY) ?? "[]") as unknown;
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

function pct(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

function AlertLineRow({
  line,
  onOpen,
  onMute,
}: {
  line: AlertLine;
  onOpen: (line: AlertLine) => void;
  onMute: (symbol: string) => void;
}) {
  const arrow = directionArrow(line.direction);
  return (
    <div
      role="button"
      tabIndex={0}
      title={line.tooltip}
      onClick={() => onOpen(line)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(line);
        }
      }}
      className={cn(
        "group grid cursor-pointer grid-cols-[2.25rem_minmax(0,1fr)_auto] items-baseline gap-x-1.5 border-l-2 py-1 pr-2 pl-1.5 outline-none hover:bg-accent/40 focus-visible:bg-accent/40",
        severityBorder(line.severity)
      )}
    >
      <span className="font-mono text-xs text-muted-foreground tabular-nums">
        {formatClock(line.atMs)}
      </span>
      <span className="flex min-w-0 items-baseline gap-1.5">
        <span className={cn("shrink-0 font-semibold", directionClass(line.direction))}>
          {arrow && <span className="mr-0.5 text-xs">{arrow}</span>}
          {line.name}
        </span>
        <span className="truncate font-mono tabular-nums">{line.label}</span>
      </span>
      <span className="flex items-center gap-1">
        {line.mutable && !line.held && (
          <button
            type="button"
            aria-label={`Mute ${line.name}`}
            title={`Mute ${line.name}`}
            className="hidden text-muted-foreground group-focus-within:inline-flex group-hover:inline-flex hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              onMute(line.symbol);
            }}
          >
            <BellOff className="size-3" />
          </button>
        )}
      </span>
      {line.detail && (
        <span className="col-span-2 col-start-2 truncate font-mono text-xs text-muted-foreground">
          {line.detail}
        </span>
      )}
    </div>
  );
}

/** Funding that is far from a market's own day. A standing note: it raises nothing. */
function FundingStrip({
  rows,
  onOpen,
}: {
  rows: readonly FundingExtremeRow[];
  onOpen?: (symbol: string) => void;
}) {
  return (
    <div className="flex shrink-0 items-baseline gap-x-2 overflow-hidden border-b border-rule px-2 py-1 font-mono text-xs">
      <span className="shrink-0 tracking-wide text-muted-foreground uppercase">Funding</span>
      {rows.length === 0 ? (
        <span className="text-muted-foreground">none extreme</span>
      ) : (
        <span className="flex min-w-0 flex-wrap gap-x-2">
          {rows.slice(0, STRIP_MAX).map((row) => (
            <button
              key={row.market_index}
              type="button"
              title={`${pairLabel(row.symbol)} funding is ${Math.abs(row.z).toFixed(1)} sigma from its own 24h`}
              className="tabular-nums hover:underline"
              onClick={() => onOpen?.(row.symbol)}
            >
              <span className="text-foreground">{row.symbol}</span>{" "}
              {/* Positive funding is longs paying, as on the Scan tables. */}
              <span className={row.funding > 0 ? "text-ask" : "text-bid"}>
                {formatFundingPct(row.funding)}
              </span>
            </button>
          ))}
          {rows.length > STRIP_MAX && (
            <span
              className="text-muted-foreground"
              title={rows
                .slice(STRIP_MAX)
                .map((row) => `${row.symbol} ${formatFundingPct(row.funding)}`)
                .join("\n")}
            >
              +{rows.length - STRIP_MAX}
            </span>
          )}
        </span>
      )}
    </div>
  );
}

interface AlertsPanelProps {
  onOpenPair?: (symbol: string) => void;
  onClose?: () => void;
}

export const AlertsPanel = memo(function AlertsPanel({ onOpenPair, onClose }: AlertsPanelProps) {
  const all = useLiveAlerts();
  const funding = useFundingExtremes();
  const [favorites] = useFavorites();
  const [minSev, setMinSev] = useState(loadMinSev);
  const [favOnly, setFavOnly] = useState(loadFavOnly);
  const [muted, setMuted] = useState(loadMuted);
  const [stats, setStats] = useState<AlertStats | null>(null);
  const seenToastRef = useRef<Set<string>>(new Set());
  const mountedAtRef = useRef(0);

  const shown = useMemo(
    () => shownAlerts(all, { minSeverity: minSev, favoritesOnly: favOnly, favorites, muted }),
    [all, minSev, favOnly, favorites, muted]
  );
  const rows = useMemo(() => shown.slice(0, MAX_ROWS), [shown]);

  useEffect(() => {
    let cancel = false;
    const load = () => {
      api
        .alertStats()
        .then((row) => {
          if (!cancel) setStats(row);
        })
        .catch(() => {});
    };
    load();
    const id = window.setInterval(load, 60_000);
    return () => {
      cancel = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!mountedAtRef.current) mountedAtRef.current = Date.now();
    const now = Date.now();
    let n = 0;
    for (const ev of shown) {
      if (n >= TOAST_MAX) break;
      if (ev.severity < URGENT || seenToastRef.current.has(ev.id)) continue;
      const at = eventMs(ev.ts);
      if (now - at < 0 || now - at > TOAST_MAX_AGE_MS || at < mountedAtRef.current - 1_000) continue;
      seenToastRef.current.add(ev.id);
      n += 1;
      notifyDesk({
        ...toastCopy(ev, pairLabel(ev.symbol)),
        tone: ev.direction === "up" ? "bid" : ev.direction === "down" ? "ask" : "warn",
        symbol: ev.symbol,
      });
    }
    if (seenToastRef.current.size > 400) {
      seenToastRef.current = new Set([...seenToastRef.current].slice(-200));
    }
  }, [shown]);

  // Which rows get opened is the most honest measure of which were worth raising.
  const open = useCallback(
    (line: AlertLine) => {
      onOpenPair?.(line.symbol);
      api.alertOpened(line.key).catch(() => {});
    },
    [onOpenPair]
  );

  const setMin = (raw: string) => {
    const n = parseInt(raw, 10);
    if (n !== NOTABLE && n !== URGENT) return;
    setMinSev(n);
    persist(MIN_SEV_KEY, String(n));
  };

  const toggleMute = (symbol: string) => {
    const next = new Set(muted);
    if (next.has(symbol)) next.delete(symbol);
    else next.add(symbol);
    setMuted(next);
    persist(MUTE_KEY, JSON.stringify([...next]));
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader
        title="Alerts"
        onClose={onClose}
        trailing={
          <FilterPopover>
            <FieldGroup className="gap-3">
              <Field>
                <FieldLabel>Show</FieldLabel>
                <ToggleGroup
                  type="single"
                  size="sm"
                  spacing={0}
                  className="w-full"
                  value={String(minSev)}
                  onValueChange={setMin}
                >
                  {SEV_CHOICES.map((c) => (
                    <ToggleGroupItem
                      key={c.value}
                      value={String(c.value)}
                      className="h-6 flex-1 px-1.5 text-xs data-[state=on]:bg-rule"
                    >
                      {c.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </Field>
              <Field orientation="horizontal" className="items-center justify-between">
                <FieldLabel htmlFor="alerts-fav-only">Favorites only</FieldLabel>
                <Switch
                  id="alerts-fav-only"
                  checked={favOnly}
                  onCheckedChange={(on) => {
                    setFavOnly(on);
                    persist(FAV_ONLY_KEY, on ? "1" : "0");
                  }}
                />
              </Field>
              {muted.size > 0 && (
                <Field>
                  <FieldLabel>Muted</FieldLabel>
                  <div className="flex flex-wrap gap-1">
                    {[...muted].map((symbol) => (
                      <Button
                        key={symbol}
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-5 gap-0.5 px-1.5 font-mono text-xs"
                        aria-label={`Unmute ${pairLabel(symbol)}`}
                        onClick={() => toggleMute(symbol)}
                      >
                        {pairLabel(symbol)}
                        <X className="size-3" />
                      </Button>
                    ))}
                  </div>
                </Field>
              )}
              {stats && (
                <Field>
                  <FieldLabel>Last 24h</FieldLabel>
                  {stats.rules.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No alerts yet.</p>
                  ) : (
                    <div className="flex flex-col gap-0.5 font-mono text-sm">
                      <div className="grid grid-cols-[minmax(0,1fr)_1.5rem_2.75rem_2.75rem_2.5rem] gap-x-1 text-muted-foreground">
                        <span />
                        <span className="text-right">n</span>
                        <span className="text-right" title="Median furthest move the alert's way in the next 15 minutes">
                          left
                        </span>
                        <span className="text-right" title="Median furthest move the other way in the next 15 minutes">
                          agst
                        </span>
                        <span className="text-right" title="Alerts you opened">
                          open
                        </span>
                      </div>
                      {stats.rules.map((row) => (
                        <div
                          key={row.rule}
                          className="grid grid-cols-[minmax(0,1fr)_1.5rem_2.75rem_2.75rem_2.5rem] gap-x-1"
                        >
                          <span className="truncate">{ruleName(row.rule)}</span>
                          <span className="text-right text-muted-foreground">{row.n}</span>
                          <span className="text-right">{pct(row.left)}</span>
                          <span className="text-right">{pct(row.against)}</span>
                          <span className="text-right text-muted-foreground">{row.opened}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </Field>
              )}
            </FieldGroup>
          </FilterPopover>
        }
      />
      <FundingStrip rows={funding} onOpen={onOpenPair} />
      <ScrollArea className="min-h-0 flex-1">
        {rows.length === 0 ? (
          <Empty className="py-8">
            <EmptyHeader>
              <EmptyTitle>Quiet</EmptyTitle>
              <EmptyDescription>
                No spike in the last hour's terms. The rest is under Scan.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          rows.map((ev) => (
            <AlertLineRow key={ev.id} line={eventLine(ev)} onOpen={open} onMute={toggleMute} />
          ))
        )}
      </ScrollArea>
    </div>
  );
});
