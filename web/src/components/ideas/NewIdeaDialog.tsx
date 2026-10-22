import { useEffect, useRef, useState } from "react";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TokenMark } from "@/components/desk/TokenMark";
import { ApiError, type Market } from "@/lib/api";
import type { IdeaBody } from "@/lib/api.gen";
import type { IdeaSeed } from "@/hooks/useIdeasPage";
import { planIssue } from "@/lib/ideas";

const THESIS = "A Thesis needs at least 10 characters.";

function perpFirst(markets: Market[]): Market[] {
  return [...markets].sort((a, b) => Number(b.is_perp) - Number(a.is_perp) || a.symbol.localeCompare(b.symbol));
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
  const listed = perpFirst(markets);
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState<"long" | "short">("long");
  const [thesis, setThesis] = useState("");
  const [tag, setTag] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [price, setPrice] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const opened = useRef(false);

  useEffect(() => {
    if (!open) {
      opened.current = false;
      return;
    }
    if (opened.current) return;
    opened.current = true;
    setSymbol(seed?.symbol ?? "");
    setSide("long");
    setThesis("");
    setTag("");
    setTags([]);
    setPrice(seed?.entry ?? "");
    setStop(seed?.stop ?? "");
    setTarget(seed?.targets[0] ?? "");
    setError("");
  }, [open, seed]);

  const why = thesis.trim();
  const plan = planIssue({
    side,
    low: price,
    high: price,
    stop,
    targets: target.trim() ? [{ price: target, pct: "" }] : [],
  });
  const ready = Boolean(symbol) && why.length >= 10 && plan == null;

  const addTag = (raw: string) => {
    const next = raw.trim().toLowerCase();
    if (!next || next.length > 24 || tags.includes(next) || tags.length >= 8) return;
    setTags([...tags, next]);
    setTag("");
  };

  const create = async () => {
    if (!ready || sending) return;
    setSending(true);
    setError("");
    const body: IdeaBody = { symbol, side, thesis: why, tags };
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
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[480px]">
        <DialogHeader>
          <DialogTitle>New idea</DialogTitle>
          <DialogDescription>An Idea never sends an order.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Market</span>
            <Combobox
              items={listed.map((market) => market.symbol)}
              value={symbol}
              onValueChange={(value) => {
                if (value) setSymbol(value);
              }}
            >
              <ComboboxInput aria-label="Market" placeholder="Market" showClear={false} />
              <ComboboxContent>
                <ComboboxEmpty>No market</ComboboxEmpty>
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
          </label>
          <ToggleGroup
            type="single"
            value={side}
            onValueChange={(value) => {
              if (value === "long" || value === "short") setSide(value);
            }}
          >
            <ToggleGroupItem value="long" className="h-6 px-2 text-xs">
              Long
            </ToggleGroupItem>
            <ToggleGroupItem value="short" className="h-6 px-2 text-xs">
              Short
            </ToggleGroupItem>
          </ToggleGroup>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Why</span>
            <Textarea
              aria-label="Why"
              rows={6}
              value={thesis}
              placeholder="Why should this work? What is the market missing?"
              onChange={(e) => setThesis(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void create();
                }
              }}
            />
            {why.length < 10 ? (
              <span className="font-mono text-muted-foreground">
                {why.length}/10 · {THESIS}
              </span>
            ) : null}
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Narratives</span>
            <span className="flex flex-wrap gap-1">
              {tags.map((item) => (
                <button key={item} type="button" className="text-muted-foreground" onClick={() => setTags(tags.filter((row) => row !== item))}>
                  {item} ×
                </button>
              ))}
            </span>
            <Input
              aria-label="Add a narrative"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addTag(tag);
                }
              }}
            />
          </label>
          <details>
            <summary>Add a plan now (optional)</summary>
            <div className="mt-2 flex flex-col gap-2">
              <Input aria-label="Entry" placeholder="Price" value={price} onChange={(e) => setPrice(e.target.value)} />
              <Input aria-label="Plan stop" placeholder="Stop" value={stop} onChange={(e) => setStop(e.target.value)} />
              <Input aria-label="Target" placeholder="Target" value={target} onChange={(e) => setTarget(e.target.value)} />
              {plan ? <p className="text-ask">{plan.message}</p> : null}
            </div>
          </details>
          {error ? <p className="text-ask">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!ready || sending} onClick={() => void create()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
