import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellOff, X } from "lucide-react";
import { notifyDesk, notifyErr } from "@/lib/notify";
import { FilterPopover } from "@/components/desk/FilterPopover";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "@/lib/api";
import {
  boardLine,
  directionArrow,
  directionClass,
  eventLine,
  eventMs,
  formatClock,
  recentEvents,
  severityBorder,
  severityText,
  toastCopy,
  type AlertLine,
} from "@/lib/alertFormat";
import {
  DEFAULT_TONE_TIMEFRAMES,
  TONE_TIMEFRAME_CAP,
  TONE_TIMEFRAME_CHOICES,
  toggleToneTimeframe,
} from "@/lib/toneTimeframes";
import { useFavorites } from "@/lib/favorites";
import { useLiveAlertBoard, useLiveAlerts } from "@/lib/liveData";
import { pairLabel } from "@/lib/venuePair";
import { cn } from "@/lib/utils";

const MIN_SEV_KEY = "mayedge-alerts-min-sev";
const FAV_ONLY_KEY = "mayedge-alerts-fav-only";
const MUTE_KEY = "mayedge-alerts-muted";
const DEFAULT_MIN_SEV = 2;
const MAX_ROWS = 80;
const LIVE_ROWS = 5;
const TOAST_SEV = 3;
const TOAST_MAX = 2;
const TOAST_MAX_AGE_MS = 8_000;

const SEV_CHOICES = [
  { value: 1, label: "All" },
  { value: 2, label: "Notable" },
  { value: 3, label: "Urgent" },
] as const;

function loadMinSev(): number {
  try {
    const n = parseInt(localStorage.getItem(MIN_SEV_KEY) ?? "", 10);
    return Number.isFinite(n) && n >= 1 && n <= 3 ? n : DEFAULT_MIN_SEV;
  } catch {
    return DEFAULT_MIN_SEV;
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

function SectionHead({ label, count }: { label: string; count: number }) {
  return (
    <div className="sticky top-0 z-10 flex items-center justify-between bg-panel px-2 pt-1.5 pb-0.5 font-mono text-xs tracking-wide text-muted-foreground uppercase">
      <span>{label}</span>
      <span className="tabular-nums">{count}</span>
    </div>
  );
}

function AlertLineRow({
  line,
  time,
  onOpen,
  onMute,
}: {
  line: AlertLine;
  time?: string;
  onOpen?: (symbol: string) => void;
  onMute: (symbol: string) => void;
}) {
  const arrow = directionArrow(line.direction);
  const open = () => onOpen?.(line.symbol);
  return (
    <div
      role="button"
      tabIndex={0}
      title={line.tooltip}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
      className={cn(
        "group grid cursor-pointer items-baseline gap-x-1.5 border-l-2 py-1 pr-2 pl-1.5 outline-none hover:bg-accent/40 focus-visible:bg-accent/40",
        time != null ? "grid-cols-[2.25rem_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)_auto]",
        severityBorder(line.severity)
      )}
    >
      {time != null && (
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{time}</span>
      )}
      <span className="flex min-w-0 items-baseline gap-1.5">
        <span className={cn("shrink-0 font-semibold", directionClass(line.direction))}>
          {arrow && <span className="mr-0.5 text-xs">{arrow}</span>}
          {pairLabel(line.symbol)}
        </span>
        <span className="truncate text-muted-foreground">{line.label}</span>
      </span>
      <span className="flex items-center gap-1">
        <button
          type="button"
          aria-label={`Mute ${pairLabel(line.symbol)}`}
          title={`Mute ${pairLabel(line.symbol)}`}
          className="hidden text-muted-foreground group-focus-within:inline-flex group-hover:inline-flex hover:text-foreground"
          onClick={(e) => {
            e.stopPropagation();
            onMute(line.symbol);
          }}
        >
          <BellOff className="size-3" />
        </button>
        {line.score != null && (
          <span className={cn("font-mono tabular-nums", severityText(line.severity))}>
            {line.score.toFixed(1)}
          </span>
        )}
      </span>
      {line.detail && (
        <span
          className={cn(
            "col-span-2 truncate font-mono text-xs text-muted-foreground",
            time != null && "col-start-2"
          )}
        >
          {line.detail}
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
  const board = useLiveAlertBoard();
  const [favorites] = useFavorites();
  const [minSev, setMinSev] = useState(loadMinSev);
  const [favOnly, setFavOnly] = useState(loadFavOnly);
  const [muted, setMuted] = useState(loadMuted);
  const [toneTfs, setToneTfs] = useState<readonly string[]>(DEFAULT_TONE_TIMEFRAMES);
  const [toneCap, setToneCap] = useState(TONE_TIMEFRAME_CAP);
  const [toneChoices, setToneChoices] = useState<readonly string[]>(TONE_TIMEFRAME_CHOICES);
  const seenToastRef = useRef<Set<string>>(new Set());
  const mountedAtRef = useRef(0);

  const isShown = useCallback(
    (symbol: string) => !muted.has(symbol) && (!favOnly || favorites.includes(symbol)),
    [muted, favOnly, favorites]
  );

  const live = useMemo(
    () =>
      board
        .filter((r) => (r.severity ?? 1) >= minSev && isShown(r.symbol))
        .slice(0, LIVE_ROWS),
    [board, minSev, isShown]
  );

  const recent = useMemo(() => {
    const liveMarkets = new Set(live.map((r) => r.market_index));
    const boardAt = Math.max(0, ...live.map((r) => eventMs(r.ts)));
    const shown = all.filter((e) => e.severity >= minSev && isShown(e.symbol));
    return recentEvents(shown, liveMarkets, boardAt).slice(0, MAX_ROWS);
  }, [all, live, minSev, isShown]);

  useEffect(() => {
    let cancel = false;
    api
      .toneTimeframes()
      .then((row) => {
        if (cancel) return;
        setToneTfs(row.timeframes);
        setToneCap(row.cap);
        if (row.choices.length) setToneChoices(row.choices);
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!mountedAtRef.current) mountedAtRef.current = Date.now();
    const now = Date.now();
    let n = 0;
    for (const ev of all) {
      if (n >= TOAST_MAX) break;
      if (ev.severity < TOAST_SEV || seenToastRef.current.has(ev.id) || !isShown(ev.symbol)) continue;
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
  }, [all, isShown]);

  const setTone = (label: string) => {
    const next = toggleToneTimeframe(toneTfs, label);
    if (next === toneTfs) return;
    setToneTfs(next);
    api
      .setToneTimeframes([...next])
      .then((row) => setToneTfs(row.timeframes))
      .catch((err: unknown) => {
        setToneTfs(toneTfs);
        notifyErr(err instanceof Error ? err.message : "Could not save timeframes");
      });
  };

  const setMin = (raw: string) => {
    const n = parseInt(raw, 10);
    if (!Number.isFinite(n) || n < 1 || n > 3) return;
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
              <Field>
                <FieldLabel>Tone timeframes</FieldLabel>
                <div className="grid grid-cols-4 gap-1">
                  {toneChoices.map((label) => {
                    const on = toneTfs.includes(label);
                    return (
                      <Button
                        key={label}
                        type="button"
                        size="sm"
                        variant={on ? "default" : "outline"}
                        aria-pressed={on}
                        disabled={!on && toneTfs.length >= toneCap}
                        onClick={() => setTone(label)}
                      >
                        {label}
                      </Button>
                    );
                  })}
                </div>
              </Field>
            </FieldGroup>
          </FilterPopover>
        }
      />
      <ScrollArea className="min-h-0 flex-1">
        {live.length === 0 && recent.length === 0 ? (
          <Empty className="py-8">
            <EmptyHeader>
              <EmptyTitle>Quiet</EmptyTitle>
              <EmptyDescription>
                Nothing unusual right now. Baselines take about 30 minutes after a restart.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <>
            {live.length > 0 && (
              <section aria-label="Live outliers">
                <SectionHead label="Live" count={live.length} />
                {live.map((row) => (
                  <AlertLineRow
                    key={row.market_index}
                    line={boardLine(row)}
                    onOpen={onOpenPair}
                    onMute={toggleMute}
                  />
                ))}
              </section>
            )}
            {recent.length > 0 && (
              <section aria-label="Recent alerts">
                <SectionHead label="Recent" count={recent.length} />
                {recent.map((ev) => {
                  const line = eventLine(ev);
                  return (
                    <AlertLineRow
                      key={ev.id}
                      line={line}
                      time={formatClock(line.atMs ?? 0)}
                      onOpen={onOpenPair}
                      onMute={toggleMute}
                    />
                  );
                })}
              </section>
            )}
          </>
        )}
      </ScrollArea>
    </div>
  );
});
