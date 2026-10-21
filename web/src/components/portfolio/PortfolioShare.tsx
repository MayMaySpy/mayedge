import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeftIcon, ChevronRightIcon, CopyIcon, DownloadIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, type PortfolioDay, type PortfolioHistory, type PortfolioNow } from "@/lib/api";
import { money, pnlClass } from "@/lib/journalFormat";
import { notifyErr, notifyOk } from "@/lib/notify";
import { CARD_HEIGHT, CARD_WIDTH, drawPnlCard, type PnlCard } from "@/lib/pnlCard";
import { PORTFOLIO_KIND_LABELS, PORTFOLIO_KINDS } from "@/lib/portfolioDay";
import { calendarMonth, cellMoney, downloadBlob, periodReturn, pnlCurve } from "@/lib/portfolioShare";
import { theme } from "@/lib/theme";
import { DESK_DATE_LOCALE } from "@/lib/utcTime";
import { cn } from "@/lib/utils";

type CardPeriod = "span" | "7d" | "30d" | "90d" | "all";

const PERIOD_LABELS: Record<Exclude<CardPeriod, "span">, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
};

function utcDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

function utcStamp(ms: number): string {
  return new Date(ms).toISOString().slice(0, 16).replace("T", " ");
}

/** W9: the PnL card: pick a range, hide the $ if you like, then save or copy it as a PNG. */
export function PnlCardDialog({
  now,
  spanLabel,
  today,
  open,
  onOpenChange,
}: {
  now: PortfolioNow;
  /** "Today" or "Last 24h": the page's own span, read from `now`. */
  spanLabel: string;
  today: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [period, setPeriod] = useState<CardPeriod>("span");
  const [showUsd, setShowUsd] = useState(true);
  const [loaded, setLoaded] = useState<{ period: CardPeriod; history: PortfolioHistory; days: PortfolioDay[] } | null>(
    null,
  );
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    const ranges = period === "span" ? (["1d", null] as const) : ([period, period] as const);
    Promise.all([api.portfolioHistory(ranges[0]), ranges[1] ? api.portfolioDays(ranges[1]) : Promise.resolve(null)])
      .then(([history, days]) => {
        if (live) setLoaded({ period, history, days: days?.days ?? [] });
      })
      .catch((e: unknown) => notifyErr(e instanceof Error ? e.message : "Failed to load the card's history"));
    return () => {
      live = false;
    };
  }, [open, period]);

  const card = useMemo<PnlCard | null>(() => {
    if (!loaded || loaded.period !== period) return null;
    if (period === "span") {
      const change = Number(now.total.change ?? "0");
      const pct = now.total.change_pct != null ? Number(now.total.change_pct) : null;
      return {
        period: spanLabel,
        dates: today ? `${utcDay(now.ts)} UTC` : `${utcStamp(now.open)} → ${utcStamp(now.ts)} UTC`,
        change,
        pct,
        showUsd,
        curve: [...pnlCurve(loaded.history, now.open).map((p) => p.pnl), change],
      };
    }
    const { change, pct } = periodReturn(loaded.days, loaded.history.points);
    const first = loaded.days[0];
    const last = loaded.days.at(-1);
    let run = 0;
    return {
      period: PERIOD_LABELS[period],
      dates: first && last ? `${first.day} → ${last.day} UTC` : "",
      change,
      pct,
      showUsd,
      curve: [0, ...loaded.days.map((d) => (run += Number(d.total ?? "0")))],
    };
  }, [loaded, period, now, spanLabel, today, showUsd]);

  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx || !card) return;
    let live = true;
    // The card's fonts are the desk's; wait for them so the first draw is not in a fallback.
    void document.fonts.ready.then(() => {
      if (live) drawPnlCard(ctx, card);
    });
    return () => {
      live = false;
    };
  }, [card]);

  const blob = () =>
    new Promise<Blob>((resolve, reject) => {
      const el = canvas.current;
      if (!el) return reject(new Error("No card to save"));
      el.toBlob((b) => (b ? resolve(b) : reject(new Error("The card did not render"))), "image/png");
    });

  const save = () =>
    blob()
      .then((b) => downloadBlob(`mayedge-pnl-${period === "span" ? (today ? "today" : "24h") : period}-${utcDay(Date.now())}.png`, b))
      .catch((e: unknown) => notifyErr(e instanceof Error ? e.message : "Save failed"));

  const copy = () =>
    blob()
      .then((b) => navigator.clipboard.write([new ClipboardItem({ "image/png": b })]))
      .then(() => notifyOk("PnL card copied"))
      .catch((e: unknown) => notifyErr(e instanceof Error ? e.message : "Copy failed"));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>PnL card</DialogTitle>
          <DialogDescription>Change net of Flows. Times are UTC.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            type="single"
            size="sm"
            value={period}
            aria-label="Card range"
            onValueChange={(value) => {
              if (value) setPeriod(value as CardPeriod);
            }}
          >
            <ToggleGroupItem value="span" className="h-6 px-2 text-xs">
              {today ? "Today" : "24h"}
            </ToggleGroupItem>
            {(["7d", "30d", "90d", "all"] as const).map((p) => (
              <ToggleGroupItem key={p} value={p} className="h-6 px-2 text-xs">
                {p === "all" ? "All" : p}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="ml-auto flex items-center gap-2">
            <Switch id="card-usd" checked={showUsd} onCheckedChange={setShowUsd} />
            <Label htmlFor="card-usd">Show $</Label>
          </div>
        </div>
        <canvas
          ref={canvas}
          width={CARD_WIDTH}
          height={CARD_HEIGHT}
          className={cn("w-full rounded-md", !card && "opacity-40")}
          aria-label="PnL card preview"
          role="img"
        />
        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" disabled={!card} onClick={copy}>
            <CopyIcon data-icon="inline-start" />
            Copy image
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={!card} onClick={save}>
            <DownloadIcon data-icon="inline-start" />
            Save PNG
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** W8: the calendar in a modal. It reads every day (`range=all`) each time it opens. */
export function CalendarDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [days, setDays] = useState<PortfolioDay[] | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    api
      .portfolioDays("all")
      .then((d) => {
        if (live) setDays(d.days);
      })
      .catch((e: unknown) => notifyErr(e instanceof Error ? e.message : "Failed to load the calendar"));
    return () => {
      live = false;
    };
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>PnL calendar</DialogTitle>
          <DialogDescription>Each UTC day's Portfolio change, net of Flows.</DialogDescription>
        </DialogHeader>
        {/* The same grid while it loads, so the modal never changes size. */}
        <PortfolioCalendar days={days ?? []} loading={days == null} />
      </DialogContent>
    </Dialog>
  );
}

/** W8: each UTC day's Portfolio change in a month grid, with the week's total at the end of its row. */
export function PortfolioCalendar({ days, loading = false }: { days: PortfolioDay[]; loading?: boolean }) {
  const today = new Date();
  const [month, setMonth] = useState({ year: today.getUTCFullYear(), month: today.getUTCMonth() });
  const first = days[0]?.day;
  const earliest = first ? { year: Number(first.slice(0, 4)), month: Number(first.slice(5, 7)) - 1 } : month;
  const atStart = month.year * 12 + month.month <= earliest.year * 12 + earliest.month;
  const atEnd = month.year * 12 + month.month >= today.getUTCFullYear() * 12 + today.getUTCMonth();
  const step = (by: number) =>
    setMonth(({ year, month: m }) => {
      const at = year * 12 + m + by;
      return { year: Math.floor(at / 12), month: at % 12 };
    });

  const weeks = useMemo(() => calendarMonth(days, month.year, month.month), [days, month]);
  const byDay = useMemo(() => new Map(days.map((d) => [d.day, d])), [days]);
  const totals = weeks.flatMap((w) => w.cells).flatMap((c) => (c?.total != null ? [c.total] : []));
  const scale = Math.max(...totals.map(Math.abs), 0);
  const monthTotal = totals.reduce((s, v) => s + v, 0);
  const label = new Date(Date.UTC(month.year, month.month, 1)).toLocaleDateString(DESK_DATE_LOCALE, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1">
          <Button type="button" variant="ghost" size="sm" className="h-6 px-1" disabled={atStart} onClick={() => step(-1)} aria-label="Previous month">
            <ChevronLeftIcon className="size-3.5" />
          </Button>
          <span className="w-36 text-center">{label}</span>
          <Button type="button" variant="ghost" size="sm" className="h-6 px-1" disabled={atEnd} onClick={() => step(1)} aria-label="Next month">
            <ChevronRightIcon className="size-3.5" />
          </Button>
        </div>
        <span className={cn("ml-auto min-w-20 text-right font-mono tabular-nums", pnlClass(String(monthTotal)))}>
          {loading ? "Loading…" : totals.length ? money(String(monthTotal)) : "—"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <div className="grid min-w-[560px] grid-cols-[repeat(7,minmax(0,1fr))_minmax(0,0.9fr)] gap-0.5" role="grid" aria-label={`PnL calendar, ${label}`}>
          {[...WEEKDAYS, "Week"].map((d) => (
            <div key={d} className="px-1.5 pb-1 text-xs text-muted-foreground" role="columnheader">
              {d}
            </div>
          ))}
          {weeks.map((week, w) => (
            <div key={w} className="contents" role="row">
              {week.cells.map((cell, i) => {
                if (!cell) return <div key={i} className="h-14 rounded-sm" role="gridcell" />;
                const v = cell.total;
                const strength = v == null || scale === 0 ? 0 : 14 + Math.round((Math.abs(v) / scale) * 46);
                const hue = v != null && v < 0 ? theme.ask : theme.bid;
                const row = byDay.get(cell.day);
                const detail = row
                  ? PORTFOLIO_KINDS.filter((k) => Number(row.kinds[k] ?? "0") !== 0)
                      .map((k) => `${PORTFOLIO_KIND_LABELS[k]} ${money(row.kinds[k])}`)
                      .join(" · ")
                  : "";
                return (
                  <div
                    key={cell.day}
                    role="gridcell"
                    title={v == null ? `${cell.day}: no data` : `${cell.day}: ${money(String(v))}${detail ? ` (${detail})` : ""}`}
                    className="flex h-14 flex-col justify-between rounded-sm bg-elevated/40 px-1.5 py-1"
                    style={strength ? { background: `color-mix(in srgb, ${hue} ${strength}%, transparent)` } : undefined}
                  >
                    <span className="text-xs text-muted-foreground">{cell.date}</span>
                    <span className="text-right font-mono text-sm tabular-nums text-text">
                      {v == null ? "" : cellMoney(v)}
                    </span>
                  </div>
                );
              })}
              <div className="flex h-14 items-end justify-end px-1.5 py-1" role="gridcell">
                <span className={cn("font-mono text-sm tabular-nums", week.total != null && pnlClass(String(week.total)))}>
                  {week.total == null ? "" : cellMoney(week.total)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
