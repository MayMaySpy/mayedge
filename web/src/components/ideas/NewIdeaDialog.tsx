import { useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { TokenMark } from "@/components/desk/TokenMark";
import { ApiError, type Market } from "@/lib/api";
import type { IdeaBody } from "@/lib/api.gen";
import type { IdeaSeed } from "@/hooks/useIdeasPage";
import { listedSymbol, planIssue } from "@/lib/ideas";
import { cn } from "@/lib/utils";

const THESIS_MIN = 10;
const TAG_MAX = 24;
const TAGS_MAX = 8;

// Perps only: a spot symbol ("rhQQQ/USDC") is no desk route and would not survive I1's upper case.
function perps(markets: Market[]): string[] {
  return markets
    .filter((market) => market.is_perp)
    .map((market) => market.symbol)
    .sort((a, b) => a.localeCompare(b));
}

export function NewIdeaDialog({
  open,
  markets,
  seed,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  markets: Market[];
  seed: IdeaSeed | null;
  onOpenChange: (open: boolean) => void;
  onCreate: (body: IdeaBody) => Promise<unknown>;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>New idea</DialogTitle>
          <DialogDescription>An Idea never sends an order.</DialogDescription>
        </DialogHeader>
        {/* Mounted with the dialog, so every open starts clean (nothing left "Creating…"). */}
        <NewIdeaForm markets={markets} seed={seed} onCancel={() => onOpenChange(false)} onCreate={onCreate} />
      </DialogContent>
    </Dialog>
  );
}

function NewIdeaForm({
  markets,
  seed,
  onCancel,
  onCreate,
}: {
  markets: Market[];
  seed: IdeaSeed | null;
  onCancel: () => void;
  onCreate: (body: IdeaBody) => Promise<unknown>;
}) {
  const listed = perps(markets);
  const seeded = seed ? (listedSymbol(listed, seed.symbol) ?? seed.symbol.toUpperCase()) : "";
  // The list portals into the form: outside the modal dialog it sits under its overlay, unclickable.
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [query, setQuery] = useState(seeded);
  const [symbol, setSymbol] = useState(seed ? listedSymbol(listed, seed.symbol) ?? "" : "");
  const [side, setSide] = useState<"long" | "short">("long");
  const [thesis, setThesis] = useState("");
  const [tag, setTag] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [planOpen, setPlanOpen] = useState(Boolean(seed?.entry || seed?.stop || seed?.targets.length));
  const [price, setPrice] = useState(seed?.entry ?? "");
  const [stop, setStop] = useState(seed?.stop ?? "");
  const [target, setTarget] = useState(seed?.targets[0] ?? "");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);

  // Markets load after the dialog can open; a typed or seeded symbol counts once it is listed.
  const chosen = symbol || listedSymbol(listed, query) || "";
  const why = thesis.trim();
  const plan = planIssue({
    side,
    low: price,
    high: price,
    stop,
    targets: target.trim() ? [{ price: target, pct: "" }] : [],
  });
  const blocker = !chosen
    ? query.trim()
      ? `${query.trim().toUpperCase()} is not a listed perp.`
      : "Pick a market."
    : why.length < THESIS_MIN
      ? `Why needs at least ${THESIS_MIN} characters (${why.length} so far).`
      : plan
        ? plan.message
        : null;

  const addTag = (raw: string): string[] => {
    const next = raw.trim().replace(/,$/, "").trim().toLowerCase();
    if (!next || next.length > TAG_MAX || tags.includes(next) || tags.length >= TAGS_MAX) return tags;
    const all = [...tags, next];
    setTags(all);
    setTag("");
    return all;
  };

  const create = async () => {
    if (blocker || sending) return;
    setSending(true);
    setError("");
    // A narrative still in the box counts; nobody expects Create to drop it.
    const body: IdeaBody = { symbol: chosen, side, thesis: why, tags: addTag(tag) };
    if (price.trim() || stop.trim() || target.trim()) {
      body.entry_low = price.trim() || null;
      body.entry_high = price.trim() || null;
      body.stop = stop.trim() || null;
      if (target.trim()) body.targets = [{ price: target.trim(), pct: null }];
    }
    try {
      await onCreate(body);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Not saved, retry");
    } finally {
      setSending(false);
    }
  };

  const submitOnMetaEnter = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void create();
    }
  };

  return (
    <div ref={setBox} className="flex flex-col gap-3" onKeyDown={submitOnMetaEnter}>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground">Market</span>
        <Combobox
          items={listed}
          value={chosen || null}
          inputValue={query}
          autoHighlight
          onInputValueChange={(text) => {
            setQuery(text);
            setSymbol(listedSymbol(listed, text) ?? "");
          }}
          onValueChange={(value) => {
            const next = typeof value === "string" ? value : "";
            setSymbol(next);
            if (next) setQuery(next);
          }}
        >
          <ComboboxInput aria-label="Market" placeholder="Type a symbol, e.g. ZRO" showClear={false} />
          <ComboboxContent container={box}>
            <ComboboxEmpty>No perp by that name</ComboboxEmpty>
            <ComboboxList>
              {(item: string) => (
                <ComboboxItem key={item} value={item}>
                  <TokenMark symbol={item} className="size-4" />
                  {item}
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground">Side</span>
        <div className="grid grid-cols-2 gap-1" role="group" aria-label="Side">
          <Button
            type="button"
            variant={side === "long" ? "buy" : "outline"}
            aria-pressed={side === "long"}
            className="h-8"
            onClick={() => setSide("long")}
          >
            Long
          </Button>
          <Button
            type="button"
            variant={side === "short" ? "sell" : "outline"}
            aria-pressed={side === "short"}
            className="h-8"
            onClick={() => setSide("short")}
          >
            Short
          </Button>
        </div>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">Why</span>
        <Textarea
          aria-label="Why"
          rows={5}
          value={thesis}
          placeholder="Why should this work? What is the market missing?"
          onChange={(e) => setThesis(e.target.value)}
        />
      </label>

      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground">Narratives</span>
        {tags.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {tags.map((item) => (
              <Badge key={item} variant="outline" className="gap-1">
                {item}
                <button
                  type="button"
                  aria-label={`Remove ${item}`}
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => setTags(tags.filter((row) => row !== item))}
                >
                  <X className="size-3" />
                </button>
              </Badge>
            ))}
          </div>
        ) : null}
        <Input
          aria-label="Add a narrative"
          placeholder={tags.length >= TAGS_MAX ? "8 narratives at most" : "ai, l2, unlock… Enter to add"}
          disabled={tags.length >= TAGS_MAX}
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              if (e.metaKey || e.ctrlKey) return;
              e.preventDefault();
              addTag(tag);
            } else if (e.key === "Backspace" && !tag && tags.length) {
              setTags(tags.slice(0, -1));
            }
          }}
        />
      </div>

      <div className="flex flex-col gap-2">
        <button
          type="button"
          aria-expanded={planOpen}
          className="inline-flex items-center gap-1 self-start text-muted-foreground hover:text-foreground"
          onClick={() => setPlanOpen(!planOpen)}
        >
          {planOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          Add a plan now (optional)
        </button>
        {planOpen ? (
          <div className="grid grid-cols-3 gap-2">
            <PlanField label="Entry" value={price} onChange={setPrice} />
            <PlanField label="Stop" value={stop} onChange={setStop} />
            <PlanField label="Target" value={target} onChange={setTarget} />
          </div>
        ) : null}
      </div>

      {error ? <p className="text-ask">{error}</p> : null}

      <DialogFooter className="items-center gap-2">
        {blocker ? (
          <span className={cn("mr-auto text-muted-foreground", plan && !planOpen ? "text-ask" : null)}>{blocker}</span>
        ) : null}
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" disabled={Boolean(blocker) || sending} onClick={() => void create()}>
          {sending ? "Creating…" : "Create"}
        </Button>
      </DialogFooter>
    </div>
  );
}

function PlanField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-muted-foreground">{label}</span>
      <Input
        aria-label={label === "Stop" ? "Plan stop" : label}
        className="font-mono"
        inputMode="decimal"
        placeholder="Price"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
