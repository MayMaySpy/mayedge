import { useEffect, useMemo, useState } from "react";
import { CalendarDaysIcon, DownloadIcon, ImageIcon } from "lucide-react";
import {
  AllocationBar,
  DaysTable,
  Holdings,
  PortfolioHero,
  ValueChart,
} from "@/components/portfolio/PortfolioParts";
import { PageNav } from "@/components/PageNav";
import { CalendarDialog, PnlCardDialog } from "@/components/portfolio/PortfolioShare";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { JournalChart } from "@/components/widgets/account/JournalChart";
import { usePortfolioPage, type PortfolioRange, type PortfolioSpan } from "@/hooks/usePortfolioPage";
import { money } from "@/lib/journalFormat";
import { heldKinds, historyKinds, PORTFOLIO_KIND_LABELS } from "@/lib/portfolioDay";
import { daysCsv, downloadText } from "@/lib/portfolioShare";

const RANGES: PortfolioRange[] = ["1d", "7d", "30d", "90d", "all"];

/** The Portfolio on its own page, at /portfolio (docs/portfolio-rules.md W1–W6). */
export function PortfolioPage() {
  const page = usePortfolioPage();
  const { now, history, days } = page;
  const [cardOpen, setCardOpen] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const spanLabel = page.span === "today" ? "Today, since 00:00 UTC" : "Last 24h";

  useEffect(() => {
    document.title = "Portfolio";
  }, []);

  const kinds = useMemo(() => (now ? heldKinds(now) : []), [now]);
  // The chart draws a kind for as long as it held money in the range, even if it holds none now.
  const charted = useMemo(() => historyKinds(history?.points ?? [], kinds), [history, kinds]);
  // Bars sit on the day's UTC midnight so the label is the viewer's own date (W5).
  const bars = useMemo(
    () =>
      days.map((day) => ({
        time: Math.floor(Date.parse(`${day.day}T00:00:00Z`) / 1000),
        net: Number(day.total ?? "0"),
      })),
    [days],
  );

  return (
    <div className="h-dvh overflow-y-auto bg-background text-base text-foreground">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-3 p-4">
        <header className="flex flex-wrap items-center gap-3">
          <PageNav current="Portfolio" />
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              size="sm"
              value={page.span}
              aria-label="Change since"
              onValueChange={(value) => {
                if (value) page.setSpan(value as PortfolioSpan);
              }}
            >
              <ToggleGroupItem value="today" className="h-6 px-2 text-xs">
                Today
              </ToggleGroupItem>
              <ToggleGroupItem value="24h" className="h-6 px-2 text-xs">
                24h
              </ToggleGroupItem>
            </ToggleGroup>
            <ToggleGroup
              type="single"
              size="sm"
              value={page.range}
              aria-label="History range"
              onValueChange={(value) => {
                if (value) page.setRange(value as PortfolioRange);
              }}
            >
              {RANGES.map((r) => (
                <ToggleGroupItem key={r} value={r} className="h-6 px-2 text-xs">
                  {r === "all" ? "All" : r}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        </header>

        {now ? (
          <>
            {now.mismatch.length > 0 ? (
              <div className="panel border-warn/40 p-3 text-warn" role="alert">
                {now.mismatch.map((m) => (
                  <div key={m.kind}>
                    {PORTFOLIO_KIND_LABELS[m.kind]}: its value less its PnL drifts from its Flows by {money(m.drift)}. A
                    venue field may have changed meaning.
                  </div>
                ))}
              </div>
            ) : null}
            <section className="relative panel flex flex-col gap-4 p-4">
              <div className="absolute top-3 right-3 flex items-center gap-1">
                <Button type="button" variant="ghost" size="sm" className="h-7" onClick={() => setCalendarOpen(true)}>
                  <CalendarDaysIcon data-icon="inline-start" />
                  Calendar
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-7" onClick={() => setCardOpen(true)}>
                  <ImageIcon data-icon="inline-start" />
                  PnL card
                </Button>
              </div>
              <PortfolioHero now={now} spanLabel={spanLabel} />
              <AllocationBar now={now} />
            </section>
            <Holdings now={now} />
            <PnlCardDialog
              now={now}
              spanLabel={page.span === "today" ? "Today" : "Last 24h"}
              today={page.span === "today"}
              open={cardOpen}
              onOpenChange={setCardOpen}
            />
            <CalendarDialog open={calendarOpen} onOpenChange={setCalendarOpen} />
          </>
        ) : (
          <section className="panel p-4 text-muted-foreground">
            {page.failed ? "The venue did not answer. Trying again each minute." : "Loading the Portfolio…"}
          </section>
        )}

        <section className="panel flex flex-col gap-1 p-2">
          <h2 className="px-2 text-muted-foreground">Value</h2>
          {history ? <ValueChart history={history} kinds={charted.length ? charted : ["perps"]} /> : null}
        </section>

        <section className="panel flex min-w-0 flex-col gap-1 p-2">
          <div className="flex items-center gap-2 px-2">
            <h2 className="text-muted-foreground">Daily change</h2>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto h-6 px-2"
              disabled={days.length === 0}
              onClick={() =>
                downloadText(`mayedge-portfolio-days-${page.range}-${new Date().toISOString().slice(0, 10)}.csv`, daysCsv(days))
              }
            >
              <DownloadIcon data-icon="inline-start" />
              Export CSV
            </Button>
          </div>
          {bars.length > 0 ? <JournalChart days={bars} height={180} label="Change" /> : null}
          <DaysTable key={page.range} days={days} kinds={charted.length ? charted : ["perps"]} />
        </section>
      </div>
    </div>
  );
}
