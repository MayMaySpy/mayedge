import { useEffect, useState } from "react";
import { ArrowLeft, Plus } from "lucide-react";
import { PageNav } from "@/components/PageNav";
import { IdeaDetail, type IdeaTab } from "@/components/ideas/IdeaDetail";
import { IdeaList } from "@/components/ideas/IdeaList";
import { NewIdeaDialog } from "@/components/ideas/NewIdeaDialog";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useIdeasPage } from "@/hooks/useIdeasPage";
import { sendDeskSymbol, sendIdeaDraft } from "@/lib/deskBridge";
import { ideaToDraft, type IdeaSort, type IdeaStatusFilter } from "@/lib/ideas";
import { keyBlocked } from "@/lib/keyTarget";
import { notifyErr, notifyOk } from "@/lib/notify";
import { utcClock } from "@/lib/utcTime";

const FILTERS: { id: IdeaStatusFilter; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "watching", label: "Watching" },
  { id: "active", label: "Active" },
  { id: "closed", label: "Closed" },
  { id: "dropped", label: "Dropped" },
  { id: "all", label: "All" },
];

const SORTS: { id: IdeaSort; label: string }[] = [
  { id: "entry", label: "Nearest entry" },
  { id: "conviction", label: "Conviction" },
  { id: "catalyst", label: "Catalyst soonest" },
  { id: "updated", label: "Updated" },
  { id: "created", label: "Created" },
  { id: "market", label: "Market A–Z" },
];

const KEYS: [string, string][] = [
  ["N", "New idea"],
  ["/", "Search"],
  ["J K", "Next and previous"],
  ["Enter", "The detail"],
  ["D", "Draft on chart"],
  ["E", "Plan"],
  ["L", "Log"],
  ["Esc", "Close, then clear search"],
];

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");
    const apply = () => setNarrow(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return narrow;
}

function filterEmpty(status: IdeaStatusFilter): string {
  const label = FILTERS.find((item) => item.id === status)?.label ?? "Open";
  if (status === "open") return "Nothing open.";
  return `Nothing ${label}.`;
}

/** The Ideas page. It never opens a socket and never sends an order (ADR 0020). */
export function IdeasPage() {
  const page = useIdeasPage();
  const narrow = useNarrow();
  const [tab, setTab] = useState<IdeaTab>("thesis");
  const [logNonce, setLogNonce] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (tab === "review" && page.selected && page.selected.status !== "closed" && page.selected.status !== "dropped") {
      setTab("thesis");
    }
  }, [page.selected, tab]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (keyBlocked(event.target)) return;
      const key = event.key;
      if (key === "n" || key === "N") {
        event.preventDefault();
        page.openCreate(null);
        return;
      }
      if (key === "/") {
        event.preventDefault();
        document.getElementById("idea-search")?.focus();
        return;
      }
      if (key === "Escape") {
        if (page.search) page.setSearch("");
        return;
      }
      const rows = page.visible;
      const index = rows.findIndex((idea) => idea.id === page.selectedId);
      if (key === "j" || key === "J" || key === "ArrowDown") {
        const next = rows[Math.min(rows.length - 1, index + 1)];
        if (next) page.setSelectedId(next.id);
        return;
      }
      if (key === "k" || key === "K" || key === "ArrowUp") {
        const next = rows[Math.max(0, index < 0 ? 0 : index - 1)];
        if (next) page.setSelectedId(next.id);
        return;
      }
      if (key === "Enter") {
        document.getElementById("idea-detail")?.focus();
        return;
      }
      if ((key === "d" || key === "D") && page.selected) {
        event.preventDefault();
        void draft(page);
        return;
      }
      if (key === "e" || key === "E") {
        setTab("plan");
        return;
      }
      if (key === "l" || key === "L") {
        setTab("log");
        setLogNonce((n) => n + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [page]);

  const suggestions = tagSuggestions(page.ideas);
  const detail = page.selected ? (
    <div id="idea-detail" tabIndex={-1} className="min-h-0 outline-none">
      <IdeaDetail
        idea={page.selected}
        log={page.log}
        market={page.marketMap.get(page.selected.symbol)}
        suggestions={suggestions}
        tab={tab}
        onTab={setTab}
        logNonce={logNonce}
        epoch={page.formEpoch}
        onPatch={(body) => page.patch(page.selected!.id, body)}
        onStatus={(body) => page.moveStatus(page.selected!.id, body)}
        onReview={(body) => page.saveReview(page.selected!.id, body)}
        onLog={(body) => page.addLog(page.selected!.id, body)}
        onDelete={() => page.remove(page.selected!.id)}
        onDraft={() => void draft(page)}
        onOpenDesk={() => void openDesk(page.selected!.symbol)}
      />
    </div>
  ) : (
    <p className="p-3 text-muted-foreground">Select an Idea.</p>
  );

  const searching = page.search.trim().length > 0;
  const noIdeas = !page.loading && page.ideas.length === 0;

  return (
    <div className="h-dvh overflow-hidden bg-background text-base text-foreground">
      <div className="mx-auto flex h-full max-w-[1680px] flex-col gap-3 p-4">
        <header className="flex flex-wrap items-center gap-2">
          <PageNav current="Ideas" />
          <ToggleGroup
            type="single"
            value={page.status}
            onValueChange={(value) => {
              if (FILTERS.some((item) => item.id === value)) page.setStatus(value as IdeaStatusFilter);
            }}
          >
            {FILTERS.map((item) => (
              <ToggleGroupItem key={item.id} value={item.id} className="h-6 px-2 text-xs">
                {item.label} <span className="text-muted-foreground">{page.counts[item.id]}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Select value={page.sort} onValueChange={(value) => page.setSort(value as IdeaSort)}>
            <SelectTrigger className="h-6" aria-label="Sort">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            id="idea-search"
            aria-label="Search ideas"
            className="h-6 w-40"
            placeholder="Search"
            value={page.search}
            onChange={(e) => page.setSearch(e.target.value)}
          />
          <Button type="button" size="sm" className="h-7" onClick={() => page.openCreate(null)}>
            <Plus data-icon="inline-start" />
            New idea
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button type="button" variant="ghost" size="sm" className="h-7" aria-label="Keyboard">
                ?
              </Button>
            </PopoverTrigger>
            <PopoverContent className="flex flex-col gap-1">
              {KEYS.map(([key, label]) => (
                <span key={key} className="flex items-center justify-between gap-3">
                  <span>{label}</span>
                  <Kbd>{key}</Kbd>
                </span>
              ))}
            </PopoverContent>
          </Popover>
        </header>
        {noIdeas ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No Ideas yet</EmptyTitle>
              <EmptyDescription>An Idea is a Market, why you want it, and where you'd be wrong.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button type="button" size="sm" className="h-7" onClick={() => page.openCreate(null)}>
                New idea
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(520px,1fr)_560px]">
            <div className="flex min-h-0 flex-col gap-2 lg:overflow-y-auto">
              {page.visible.length === 0 && !page.loading ? (
                <div className="flex flex-col gap-2 p-3">
                  <p>{searching ? `No Idea matches '${page.search.trim()}'.` : filterEmpty(page.status)}</p>
                  {searching ? null : (
                    <button type="button" className="self-start text-muted-foreground" onClick={() => page.setStatus("all")}>
                      All
                    </button>
                  )}
                </div>
              ) : (
                <IdeaList
                  ideas={page.visible}
                  markets={page.marketMap}
                  sort={page.sort}
                  onSort={page.setSort}
                  selectedId={page.selectedId}
                  onSelect={page.setSelectedId}
                  now={now}
                />
              )}
            </div>
            <div className="hidden h-full min-h-0 lg:block lg:overflow-y-auto">{detail}</div>
          </div>
        )}
        <Sheet
          open={narrow && page.selected != null}
          onOpenChange={(open) => {
            if (!open) page.setSelectedId(null);
          }}
        >
          <SheetContent side="right" className="w-full sm:max-w-full">
            <SheetTitle className="sr-only">{page.selected ? `${page.selected.symbol} ${page.selected.side}` : "Idea"}</SheetTitle>
            <Button type="button" variant="ghost" size="sm" className="h-7" onClick={() => page.setSelectedId(null)}>
              <ArrowLeft data-icon="inline-start" />
              Back
            </Button>
            {detail}
          </SheetContent>
        </Sheet>
        <NewIdeaDialog
          open={page.creating}
          markets={page.markets}
          seed={page.seed}
          onOpenChange={page.setCreating}
          onCreate={page.create}
        />
      </div>
    </div>
  );
}

function tagSuggestions(ideas: { tags: string[] }[]): string[] {
  const counts = new Map<string, number>();
  for (const idea of ideas) {
    for (const tag of idea.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([tag]) => tag);
}

async function draft(page: ReturnType<typeof useIdeasPage>) {
  const idea = page.selected;
  if (!idea) return;
  const chart = ideaToDraft(idea, page.marketMap.get(idea.symbol)?.price_decimals ?? 4);
  if (!chart) return;
  try {
    const where = await sendIdeaDraft(idea.symbol, idea.id, chart);
    const when = utcClock(Date.now(), false);
    notifyOk(
      where === "desk" ? "Draft sent to the desk tab" : "Opened a desk tab",
      `Draft from the plan as of ${when} UTC`,
      idea.symbol,
    );
  } catch (e) {
    notifyErr(e instanceof Error ? e.message : "The draft was not sent");
  }
}

async function openDesk(symbol: string) {
  try {
    await sendDeskSymbol(symbol);
  } catch (e) {
    notifyErr(e instanceof Error ? e.message : "The desk did not switch");
  }
}
