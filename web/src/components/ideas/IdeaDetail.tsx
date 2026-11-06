import { useEffect, useRef, useState, type RefObject } from "react";
import { Ellipsis } from "lucide-react";
import { TokenMark } from "@/components/desk/TokenMark";
import { IdeaAlerts } from "@/components/ideas/IdeaAlerts";
import { IdeaChart } from "@/components/ideas/IdeaChart";
import { IdeaPlanForm } from "@/components/ideas/IdeaPlanForm";
import { IdeaZoneBar } from "@/components/ideas/IdeaZoneBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, api, type Market } from "@/lib/api";
import type { Idea, IdeaCatalyst, IdeaLogLine, IdeaPatch, IdeaReviewBody, IdeaStatusBody, JournalTrip } from "@/lib/api.gen";
import { useIdeaAlerts } from "@/hooks/useIdeaAlerts";
import { armedCount } from "@/lib/ideaAlerts";
import { ideaTrips, marketLast, planComplete } from "@/lib/ideas";
import { money, price, rValue, size } from "@/lib/journalFormat";
import { utcDateTime } from "@/lib/utcTime";
import { cn, signClass } from "@/lib/utils";

export type IdeaTab = "thesis" | "plan" | "alerts" | "log" | "trades" | "review";

const STATUS = { watching: "Watching", active: "Active", closed: "Closed", dropped: "Dropped" } as const;
const OUTCOME = [
  ["worked", "Worked"],
  ["failed", "Failed"],
  ["missed", "Missed"],
  ["wrong", "Wrong"],
] as const;
const KIND = { update: "✎", plan: "⇢", status: "●", planner: "▶", alert: "🔔" } as const;

function Linked({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/\S+)/g);
  return parts.map((part, i) =>
    part.startsWith("http://") || part.startsWith("https://") ? (
      <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="underline">
        {part}
      </a>
    ) : (
      part
    ),
  );
}

type Outcome = NonNullable<Idea["outcome"]>;

function savedLine(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return e.message;
  return "Not saved, retry";
}

export function IdeaDetail({
  idea,
  log,
  market,
  suggestions,
  tab,
  onTab,
  logNonce,
  epoch,
  onPatch,
  onStatus,
  onReview,
  onLog,
  onDelete,
  onDraft,
  onOpenDesk,
}: {
  idea: Idea;
  log: IdeaLogLine[];
  market: Market | undefined;
  suggestions: string[];
  tab: IdeaTab;
  onTab: (tab: IdeaTab) => void;
  logNonce: number;
  epoch: number;
  onPatch: (body: Omit<IdeaPatch, "seen_updated_at">) => Promise<Idea>;
  onStatus: (body: IdeaStatusBody) => Promise<unknown>;
  onReview: (body: IdeaReviewBody) => Promise<unknown>;
  onLog: (body: string) => Promise<unknown>;
  onDelete: () => Promise<void>;
  onDraft: () => void;
  onOpenDesk: () => void;
}) {
  const [reviewFor, setReviewFor] = useState<null | { status: "closed" | "dropped"; outcome: Outcome }>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const last = marketLast(market);
  const ready = planComplete(idea);
  const ended = idea.status === "closed" || idea.status === "dropped";
  const [trips, setTrips] = useState<JournalTrip[]>([]);
  const composer = useRef<HTMLTextAreaElement>(null);
  const priceAlerts = useIdeaAlerts(idea.id);

  useEffect(() => {
    let live = true;
    void api
      .journalTrips({
        market: idea.symbol,
        since: idea.created_at,
        until: idea.closed_at ?? undefined,
      })
      .then((body) => {
        if (live) setTrips(ideaTrips(body.trips, idea));
      })
      .catch(() => {
        if (live) setTrips([]);
      });
    return () => {
      live = false;
    };
  }, [idea]);

  useEffect(() => {
    if (tab === "log") composer.current?.focus();
  }, [tab, logNonce]);

  const copy = async () => {
    const lines = [`# ${idea.symbol} ${idea.side}`, "", idea.thesis];
    if (idea.plan_entry && idea.stop && idea.r) {
      lines.push("", `Plan: entry ${idea.plan_entry}, stop ${idea.stop}, R ${idea.r}`);
    }
    if (idea.invalidation) lines.push("", `Invalidation: ${idea.invalidation}`);
    if (idea.trigger) lines.push("", `Trigger: ${idea.trigger}`);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
    } catch {
      /* the menu stays; the operator can try again */
    }
  };

  return (
    <div className="flex min-h-0 flex-col gap-3 overflow-y-auto rounded-lg border border-rule bg-panel p-3">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <TokenMark symbol={idea.symbol} />
            <span className="font-sans text-lg">{idea.symbol}</span>
            <Badge variant={idea.side === "long" ? "bid" : "ask"}>{idea.side === "long" ? "Long" : "Short"}</Badge>
            <Badge variant="outline">{STATUS[idea.status]}</Badge>
            <span className="inline-flex gap-0.5" aria-label={`Conviction ${idea.conviction}`}>
              {[1, 2, 3].map((n) => (
                <button
                  key={n}
                  type="button"
                  aria-label={`Conviction ${n}`}
                  className={cn("size-2 rounded-full", n <= idea.conviction ? "bg-foreground" : "bg-muted-foreground/30")}
                  onClick={() => void onPatch({ conviction: n })}
                />
              ))}
            </span>
            <Select value={idea.horizon} onValueChange={(value) => {
              if (value === "scalp" || value === "swing" || value === "position") void onPatch({ horizon: value });
            }}>
              <SelectTrigger className="h-6" aria-label="Horizon">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="scalp">Scalp</SelectItem>
                <SelectItem value="swing">Swing</SelectItem>
                <SelectItem value="position">Position</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p className="line-clamp-2 font-sans text-muted-foreground">
            <Linked text={idea.thesis} />
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Button type="button" size="sm" className="h-7" disabled={!ready} onClick={onDraft}>
                  Draft on chart
                </Button>
              </span>
            </TooltipTrigger>
            {ready ? null : <TooltipContent>Needs an entry and a stop</TooltipContent>}
          </Tooltip>
          {idea.status === "watching" ? (
            <Button type="button" variant="outline" size="sm" className="h-7" onClick={() => void onStatus({ status: "active" })}>
              Mark active
            </Button>
          ) : null}
          {idea.status === "active" ? (
            <Button type="button" variant="outline" size="sm" className="h-7" onClick={() => setReviewFor({ status: "closed", outcome: "worked" })}>
              Close
            </Button>
          ) : null}
          {idea.status === "watching" || idea.status === "active" ? (
            <Button type="button" variant="ghost" size="sm" className="h-7" onClick={() => setReviewFor({ status: "dropped", outcome: "wrong" })}>
              Drop
            </Button>
          ) : null}
          {ended ? (
            <Button type="button" variant="outline" size="sm" className="h-7" onClick={() => void onStatus({ status: "watching" })}>
              Reopen
            </Button>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="sm" className="h-7" aria-label="More">
                <Ellipsis />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={onOpenDesk}>Open on desk</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void copy()}>Copy as text</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setConfirmDelete(true)}>Delete</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <IdeaZoneBar idea={idea} last={last} onEditPlan={() => onTab("plan")} />
      <IdeaChart idea={idea} market={market} onOpenDesk={onOpenDesk} />
      <Tabs value={tab} onValueChange={(value) => onTab(value as IdeaTab)}>
        <TabsList>
          <TabsTrigger value="thesis">Thesis</TabsTrigger>
          <TabsTrigger value="plan">Plan</TabsTrigger>
          <TabsTrigger value="alerts">Alerts {armedCount(priceAlerts.alerts)}</TabsTrigger>
          <TabsTrigger value="log">Log {log.length}</TabsTrigger>
          <TabsTrigger value="trades">Trades {trips.length}</TabsTrigger>
          {ended ? <TabsTrigger value="review">Review</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="thesis">
          <Thesis idea={idea} suggestions={suggestions} onPatch={onPatch} />
        </TabsContent>
        <TabsContent value="plan">
          <IdeaPlanForm
            key={`${idea.id}:${epoch}`}
            idea={idea}
            decimals={market?.price_decimals ?? 4}
            last={last}
            onSave={onPatch}
          />
        </TabsContent>
        <TabsContent value="alerts">
          <IdeaAlerts idea={idea} last={last} alerts={priceAlerts.alerts} onChanged={priceAlerts.reload} />
        </TabsContent>
        <TabsContent value="log">
          <Log log={log} composer={composer} onLog={onLog} />
        </TabsContent>
        <TabsContent value="trades">
          <Trades idea={idea} trips={trips} />
        </TabsContent>
        {ended ? (
          <TabsContent value="review">
            <Review idea={idea} trips={trips} onReview={onReview} />
          </TabsContent>
        ) : null}
      </Tabs>
      {reviewFor ? (
        <ReviewDialog
          idea={idea}
          status={reviewFor.status}
          outcome={reviewFor.outcome}
          onOpenChange={(open) => {
            if (!open) setReviewFor(null);
          }}
          onStatus={async (body) => {
            await onStatus(body);
            setReviewFor(null);
          }}
        />
      ) : null}
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {idea.symbol} {idea.side}</DialogTitle>
            <DialogDescription>
              Delete {idea.symbol} {idea.side} and its {log.length} {log.length === 1 ? "log line" : "log lines"}? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                // A failure toasts in the page and keeps this dialog open (S6).
                void onDelete().then(() => setConfirmDelete(false), () => undefined);
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Thesis({
  idea,
  suggestions,
  onPatch,
}: {
  idea: Idea;
  suggestions: string[];
  onPatch: (body: Omit<IdeaPatch, "seen_updated_at">) => Promise<Idea>;
}) {
  const [text, setText] = useState(idea.thesis);
  const [invalidation, setInvalidation] = useState(idea.invalidation);
  const [tags, setTags] = useState(idea.tags);
  const [tag, setTag] = useState("");
  const [catalysts, setCatalysts] = useState<IdeaCatalyst[]>(idea.catalysts);
  const [note, setNote] = useState("");
  const server = useRef(idea);
  useEffect(() => {
    const prev = server.current;
    if (idea.id !== prev.id) {
      setText(idea.thesis);
      setInvalidation(idea.invalidation);
      setTags(idea.tags);
      setCatalysts(idea.catalysts);
      setNote("");
    } else if (idea.updated_at !== prev.updated_at) {
      if (text === prev.thesis) setText(idea.thesis);
      if (invalidation === prev.invalidation) setInvalidation(idea.invalidation);
      if (tags.join("\0") === prev.tags.join("\0")) setTags(idea.tags);
      if (JSON.stringify(catalysts) === JSON.stringify(prev.catalysts)) setCatalysts(idea.catalysts);
    }
    server.current = idea;
  }, [idea, text, invalidation, tags, catalysts]);

  const save = async (body: Omit<IdeaPatch, "seen_updated_at">) => {
    try {
      const saved = await onPatch(body);
      setNote("Saved");
      return saved;
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Not saved, retry");
      throw e;
    }
  };

  const saveThesis = async () => {
    const next = text.trim();
    if (next === idea.thesis) return;
    if (next.length < 10) {
      setNote("A Thesis needs at least 10 characters.");
      setText(idea.thesis);
      return;
    }
    try {
      await save({ thesis: next });
    } catch {
      setText(idea.thesis);
    }
  };

  const addTag = (raw: string) => {
    const next = raw.trim().toLowerCase();
    if (!next) return;
    if (next.length > 24) {
      setNote("A tag is 1–24 characters.");
      return;
    }
    if (tags.length >= 8) {
      setNote("An Idea has at most 8 tags.");
      return;
    }
    if (tags.includes(next)) {
      setTag("");
      return;
    }
    const added = [...tags, next];
    setTags(added);
    setTag("");
    void save({ tags: added }).catch(() => setTags(idea.tags));
  };

  return (
    <div className="flex flex-col gap-3 pt-2">
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">Why</span>
        <Textarea
          aria-label="Why"
          rows={Math.min(16, Math.max(6, text.split("\n").length))}
          value={text}
          placeholder="Why should this work? What is the market missing?"
          onChange={(e) => setText(e.target.value)}
          onBlur={() => void saveThesis()}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void saveThesis();
            }
          }}
        />
      </label>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground">Narratives</span>
        <span className="flex flex-wrap gap-1">
          {tags.map((item) => (
            <button
              key={item}
              type="button"
              className="rounded-md border border-border px-1.5 text-muted-foreground"
              onClick={() => {
                const next = tags.filter((row) => row !== item);
                setTags(next);
                void save({ tags: next }).catch(() => setTags(idea.tags));
              }}
            >
              {item} ×
            </button>
          ))}
        </span>
        <Input
          aria-label="Add a narrative"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          onBlur={() => {
            if (tag.trim()) addTag(tag);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addTag(tag);
            } else if (e.key === "Backspace" && !tag && tags.length) {
              const next = tags.slice(0, -1);
              setTags(next);
              void save({ tags: next }).catch(() => setTags(idea.tags));
            }
          }}
        />
        <span className="flex flex-wrap gap-1">
          {suggestions
            .filter((item) => item.includes(tag.trim().toLowerCase()) && !tags.includes(item))
            .slice(0, 6)
            .map((item) => (
              <button key={item} type="button" className="text-muted-foreground" onMouseDown={(e) => e.preventDefault()} onClick={() => addTag(item)}>
                {item}
              </button>
            ))}
        </span>
      </div>
      <Catalysts
        rows={catalysts}
        saved={idea.catalysts}
        onEdit={setCatalysts}
        onSave={async (next) => {
          const saved = await save({ catalysts: next });
          return saved.catalysts;
        }}
        onNote={setNote}
      />
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">Invalidation</span>
        <Textarea
          aria-label="Invalidation"
          rows={3}
          value={invalidation}
          placeholder="What would prove this wrong, besides the stop?"
          onChange={(e) => setInvalidation(e.target.value)}
          onBlur={() => {
            if (invalidation !== idea.invalidation) {
              void save({ invalidation }).catch(() => setInvalidation(idea.invalidation));
            }
          }}
        />
      </label>
      {note ? <p className="text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function cleanCatalysts(rows: IdeaCatalyst[]): IdeaCatalyst[] {
  return rows.flatMap((row) => {
    const text = row.text.trim();
    if (!text) return [];
    return [{ text, date: row.date || null, time: row.time || null, url: row.url?.trim() || null }];
  });
}

function Catalysts({
  rows,
  saved,
  onEdit,
  onSave,
  onNote,
}: {
  rows: IdeaCatalyst[];
  saved: IdeaCatalyst[];
  onEdit: (rows: IdeaCatalyst[]) => void;
  onSave: (rows: IdeaCatalyst[]) => Promise<IdeaCatalyst[]>;
  onNote: (note: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const edit = (index: number, patch: Partial<IdeaCatalyst>) =>
    onEdit(rows.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  const persist = async (next: IdeaCatalyst[]) => {
    onEdit(next);
    const clean = cleanCatalysts(next);
    if (JSON.stringify(clean) === JSON.stringify(saved)) return;
    try {
      const stored = await onSave(clean);
      onEdit([...stored, ...next.filter((row) => !row.text.trim())]);
    } catch {
      // The note already says why. The row stays so a bad link can be fixed.
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <span className="text-muted-foreground">Catalysts, UTC</span>
      {rows.map((row, index) => {
        const soon = row.date != null && row.date >= today && Date.parse(`${row.date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`) <= 7 * 86_400_000;
        const past = row.date != null && row.date < today;
        const days = row.date ? Math.round((Date.parse(`${row.date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000) : null;
        const link = row.url?.trim() ?? "";
        const open = /^https?:\/\/\S+$/.test(link);
        return (
          <div key={index} className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
              <Input
                aria-label="Catalyst date"
                type="date"
                className="h-7 w-36"
                value={row.date ?? ""}
                onChange={(e) => {
                  const date = e.target.value || null;
                  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
                  void persist(rows.map((item, i) => (i === index ? { ...item, date } : item)));
                }}
              />
              <Input
                aria-label="Catalyst time"
                type="time"
                className="h-7 w-28"
                value={row.time ?? ""}
                onChange={(e) => {
                  const time = e.target.value ? e.target.value.slice(0, 5) : null;
                  void persist(rows.map((item, i) => (i === index ? { ...item, time } : item)));
                }}
              />
              {soon && days != null ? <span className="text-warn">{days === 0 ? "today" : `in ${days}d`}</span> : null}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6"
                aria-label="Remove catalyst"
                onClick={() => void persist(rows.filter((_, i) => i !== index))}
              >
                ×
              </Button>
            </div>
            <Input
              aria-label="Catalyst"
              className={cn("h-7", past && "text-muted-foreground")}
              value={row.text}
              placeholder="Unlock, listing, vote"
              onChange={(e) => edit(index, { text: e.target.value })}
              onBlur={(e) =>
                void persist(rows.map((item, i) => (i === index ? { ...item, text: e.target.value } : item)))
              }
            />
            <div className="flex items-center gap-2">
              <Input
                aria-label="Catalyst link"
                className="h-7"
                value={row.url ?? ""}
                placeholder="https://"
                onChange={(e) => edit(index, { url: e.target.value || null })}
                onBlur={(e) =>
                  void persist(rows.map((item, i) => (i === index ? { ...item, url: e.target.value || null } : item)))
                }
              />
              {open ? (
                <a href={link} target="_blank" rel="noopener noreferrer" className="shrink-0 underline">
                  Open
                </a>
              ) : null}
            </div>
          </div>
        );
      })}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-6 self-start"
        onClick={() => {
          if (rows.length >= 12) {
            onNote("An Idea has at most 12 catalysts.");
            return;
          }
          onEdit([...rows, { text: "", date: null, time: null, url: null }]);
        }}
      >
        Add catalyst
      </Button>
    </div>
  );
}

function Log({
  log,
  composer,
  onLog,
}: {
  log: IdeaLogLine[];
  composer: RefObject<HTMLTextAreaElement | null>;
  onLog: (body: string) => Promise<unknown>;
}) {
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const add = async () => {
    const body = text.trim();
    if (!body) return;
    try {
      await onLog(body);
      setText("");
      setNote("Saved");
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Not saved, retry");
    }
  };
  return (
    <div className="flex flex-col gap-2 pt-2">
      <Textarea
        ref={composer}
        aria-label="What changed?"
        rows={2}
        value={text}
        placeholder="What changed?"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void add();
          }
        }}
      />
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" className="h-7" onClick={() => void add()}>
          Add
        </Button>
        {note ? <span className="text-muted-foreground">{note}</span> : null}
      </div>
      {log.length === 0 ? <p className="text-muted-foreground">No log lines yet.</p> : null}
      <ul className="flex flex-col gap-2">
        {log.map((line) => (
          <li key={line.id} className="flex flex-col gap-0.5">
            <span className="font-mono text-muted-foreground">
              {KIND[line.kind]} {utcDateTime(line.ts)} UTC
              {line.last ? ` · ${price(line.last)}` : ""}
            </span>
            <span className="font-sans">{line.body}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Trades({ idea, trips }: { idea: Idea; trips: JournalTrip[] }) {
  const net = trips.reduce((sum, trip) => sum + (Number(trip.net) || 0), 0);
  if (trips.length === 0) {
    return <p className="pt-2 text-muted-foreground">No Round trips on {idea.symbol} since this Idea was made.</p>;
  }
  return (
    <div className="flex flex-col gap-2 pt-2">
      <table className="w-full">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th>Opened</th>
            <th>Side</th>
            <th>Size</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>Net</th>
            <th>R</th>
          </tr>
        </thead>
        <tbody>
          {trips.map((trip) => (
            <tr key={trip.trip_key}>
              <td className="font-mono">{utcDateTime(trip.open_ts)} UTC</td>
              <td>{trip.side}</td>
              <td className="font-mono">{size(trip.size)}</td>
              <td className="font-mono">{price(trip.avg_in)}</td>
              <td className="font-mono">{price(trip.avg_out)}</td>
              <td className={cn("font-mono", signClass(Number(trip.net)))}>{money(trip.net)}</td>
              <td className="font-mono">{trip.r ? rValue(trip.r) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="font-mono">
        {trips.length} {trips.length === 1 ? "Round trip" : "Round trips"} · Net{" "}
        <span className={signClass(net)}>{money(String(net))}</span> ·{" "}
        <a href="/journal" className="text-muted-foreground">
          Open in Journal
        </a>
      </p>
    </div>
  );
}

function Review({
  idea,
  trips,
  onReview,
}: {
  idea: Idea;
  trips: JournalTrip[];
  onReview: (body: IdeaReviewBody) => Promise<unknown>;
}) {
  const [outcome, setOutcome] = useState(idea.outcome ?? "");
  const [text, setText] = useState(idea.review);
  const [note, setNote] = useState("");
  const days = idea.closed_at == null ? null : Math.max(0, Math.round((idea.closed_at - idea.created_at) / 86_400_000));
  const net = trips.reduce((sum, trip) => sum + (Number(trip.net) || 0), 0);
  const rs = trips.map((trip) => Number(trip.r)).filter((n) => Number.isFinite(n));
  const rTotal = rs.length ? rs.reduce((sum, n) => sum + n, 0) : null;
  useEffect(() => {
    setOutcome(idea.outcome ?? "");
    setText(idea.review);
  }, [idea.id, idea.updated_at, idea.outcome, idea.review]);

  const save = async (body: IdeaReviewBody) => {
    try {
      await onReview(body);
      setNote("Saved");
    } catch (e) {
      setNote(savedLine(e));
    }
  };

  return (
    <div className="flex flex-col gap-2 pt-2">
      <p className="font-mono text-muted-foreground">
        {days == null ? "Still open" : `Open ${days}d`} · Net {money(String(net))}
        {rTotal == null ? "" : ` · ${rValue(String(rTotal))}`}
      </p>
      <div className="flex gap-1">
        {OUTCOME.map(([value, label]) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={outcome === value ? "default" : "outline"}
            className="h-6"
            onClick={() => {
              setOutcome(value);
              void save({ outcome: value });
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      <Textarea
        aria-label="What did this teach you?"
        rows={4}
        value={text}
        placeholder="What did this teach you?"
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (text !== idea.review) void save({ review: text });
        }}
      />
      {note ? <p className="text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function ReviewDialog({
  idea,
  status,
  outcome,
  onOpenChange,
  onStatus,
}: {
  idea: Idea;
  status: "closed" | "dropped";
  outcome: Outcome;
  onOpenChange: (open: boolean) => void;
  onStatus: (body: IdeaStatusBody) => Promise<void>;
}) {
  const [picked, setPicked] = useState<Outcome>(outcome);
  const [text, setText] = useState("");
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{status === "closed" ? "Close" : "Drop"} {idea.symbol} {idea.side}</DialogTitle>
          <DialogDescription>A Review is optional. Skip leaves it blank.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-1">
          {OUTCOME.map(([value, label]) => (
            <Button key={value} type="button" size="sm" variant={picked === value ? "default" : "outline"} className="h-6" onClick={() => setPicked(value)}>
              {label}
            </Button>
          ))}
        </div>
        <Textarea aria-label="What did this teach you?" rows={3} value={text} placeholder="What did this teach you?" onChange={(e) => setText(e.target.value)} />
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => void onStatus({ status })}>
            Skip
          </Button>
          <Button type="button" onClick={() => void onStatus({ status, outcome: picked, review: text })}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
