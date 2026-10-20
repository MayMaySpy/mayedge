import { ExternalLinkIcon } from "lucide-react";
import { JournalChart } from "@/components/widgets/account/JournalChart";
import { JournalControls, JournalStats, JournalTrips } from "@/components/journal/JournalParts";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useJournal } from "@/hooks/useJournal";
import { JOURNAL_PATH } from "@/lib/deskRoute";

export function JournalTab({ active }: { active: boolean }) {
  const journal = useJournal({ active });
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 text-base">
      <div className="flex items-center gap-2 px-2 pt-2">
        <JournalControls journal={journal} className="min-w-0 flex-1" />
        <a
          href={JOURNAL_PATH}
          target="_blank"
          rel="noopener"
          className="inline-flex shrink-0 items-center gap-1 text-muted-foreground hover:text-foreground"
        >
          Open page
          <ExternalLinkIcon className="size-3" aria-hidden />
        </a>
      </div>
      <JournalStats strip={journal.strip} className="px-2" />
      {journal.bars.length > 0 ? <JournalChart days={journal.bars} /> : null}
      <ScrollArea className="min-h-0 flex-1">
        <JournalTrips journal={journal} />
      </ScrollArea>
    </div>
  );
}
