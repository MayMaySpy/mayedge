import { useEffect, useState } from "react";
import { RefreshCwIcon } from "lucide-react";
import { JournalChart } from "@/components/widgets/account/JournalChart";
import {
  JournalBreakdown,
  JournalControls,
  JournalStats,
  JournalTrips,
} from "@/components/journal/JournalParts";
import { PageNav } from "@/components/PageNav";
import { Button } from "@/components/ui/button";
import { useJournal } from "@/hooks/useJournal";
import { api } from "@/lib/api";
import { setMarketDecimals } from "@/lib/marketFormat";

/** The Journal on its own page, at /journal. REST only: it holds no desk socket. */
export function JournalPage() {
  const journal = useJournal({ active: true, breakdowns: true });

  // Prices show at each market's tick. The desk serves the list from memory.
  const [, setTicks] = useState(0);
  useEffect(() => {
    document.title = "Journal";
    api
      .markets()
      .then((markets) => {
        setMarketDecimals(markets);
        setTicks((n) => n + 1);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="h-dvh overflow-y-auto bg-background text-base text-foreground">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-3 p-4">
        <header className="flex flex-wrap items-center gap-3">
          <PageNav current="Journal" />
          <JournalControls journal={journal} className="ml-auto" />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            disabled={journal.loading}
            onClick={journal.reload}
            aria-label="Reload"
          >
            <RefreshCwIcon className={journal.loading ? "size-3.5 animate-spin" : "size-3.5"} aria-hidden />
          </Button>
        </header>

        <section className="panel p-3">
          <JournalStats strip={journal.strip} full />
        </section>

        {journal.bars.length > 0 ? (
          <section className="panel p-2">
            <JournalChart days={journal.bars} height={240} />
          </section>
        ) : null}

        <div className="grid gap-3 md:grid-cols-2">
          <div className="panel p-1">
            <JournalBreakdown title="By market" column="Market" groups={journal.byMarket} total={journal.strip} />
          </div>
          <div className="panel p-1">
            <JournalBreakdown title="By algo" column="Algo" groups={journal.byAlgo} total={journal.strip} />
          </div>
        </div>

        <section className="panel overflow-x-auto p-1">
          <JournalTrips journal={journal} />
        </section>
      </div>
    </div>
  );
}
