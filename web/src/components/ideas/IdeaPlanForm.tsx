import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CellInput } from "@/components/widgets/CellInput";
import { ApiError } from "@/lib/api";
import type { Idea, IdeaPatch, IdeaTargetIn } from "@/lib/api.gen";
import { planIssue, planReadout, priceAtR, rAtPrice, type PlanInput, type PlanIssue } from "@/lib/ideas";
import { snapTick } from "@/lib/ticketAmend";

type TargetDraft = { mode: "price" | "r"; value: string; pct: string };

type Draft = {
  mode: "zone" | "price";
  low: string;
  high: string;
  price: string;
  stop: string;
  targets: TargetDraft[];
  trigger: string;
};

function fromIdea(idea: Idea): Draft {
  const single = idea.entry_low != null && idea.entry_low === idea.entry_high;
  return {
    mode: single ? "price" : "zone",
    low: idea.entry_low ?? "",
    high: idea.entry_high ?? "",
    price: single ? (idea.entry_low ?? "") : "",
    stop: idea.stop ?? "",
    targets: idea.targets.map((target) => ({ mode: "price", value: target.price, pct: target.pct ?? "" })),
    trigger: idea.trigger,
  };
}

function planInput(draft: Draft, side: Idea["side"], decimals: number): PlanInput {
  const low = draft.mode === "price" ? draft.price : draft.low;
  const high = draft.mode === "price" ? draft.price : draft.high;
  const entry = low && high ? String((Number(low) + Number(high)) / 2) : low;
  return {
    side,
    low,
    high,
    stop: draft.stop,
    targets: draft.targets
      .filter((row) => row.value.trim() || row.pct.trim())
      .map((row) => ({
        price: row.mode === "r" ? (priceAtR(entry, draft.stop, side, row.value, decimals) ?? "") : row.value,
        pct: row.pct,
      })),
  };
}

function targetsOf(input: PlanInput): IdeaTargetIn[] {
  return input.targets
    .filter((row) => row.price.trim())
    .map((row) => ({ price: row.price.trim(), pct: row.pct.trim().replace(/%$/, "") || null }));
}

export function IdeaPlanForm({
  idea,
  decimals,
  last,
  onSave,
}: {
  idea: Idea;
  decimals: number;
  last: number | null;
  onSave: (body: Omit<IdeaPatch, "seen_updated_at">) => Promise<Idea>;
}) {
  const [draft, setDraft] = useState(() => fromIdea(idea));
  const [server, setServer] = useState<PlanIssue | null>(null);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);

  const input = planInput(draft, idea.side, decimals);
  const issue = planIssue(input) ?? server;
  const read = planReadout(input);
  const lastText = last == null ? null : snapTick(last, decimals);
  const set = (patch: Partial<Draft>) => {
    setServer(null);
    setDraft((row) => ({ ...row, ...patch }));
  };

  const save = async () => {
    if (issue || sending) return;
    const low = input.low.trim();
    const high = input.high.trim();
    setSending(true);
    setNote("");
    try {
      await onSave({
        entry_low: low || null,
        entry_high: high || null,
        stop: input.stop.trim() || null,
        targets: targetsOf(input),
        trigger: draft.trigger,
      });
      setNote("Saved");
    } catch (e) {
      if (e instanceof ApiError && e.field) setServer({ field: e.field, message: e.message });
      setNote(e instanceof ApiError && e.status === 409 ? e.message : "Not saved, retry");
    } finally {
      setSending(false);
    }
  };

  const fieldNote = (field: string) => (issue?.field === field ? issue.message : null);

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="flex items-center gap-2">
        <ToggleGroup
          type="single"
          value={draft.mode}
          onValueChange={(value) => {
            if (value === "zone") set({ mode: "zone", low: draft.price || draft.low, high: draft.price || draft.high });
            if (value === "price") set({ mode: "price", price: draft.low || draft.price });
          }}
        >
          <ToggleGroupItem value="zone" className="h-6 px-2 text-xs">
            Zone
          </ToggleGroupItem>
          <ToggleGroupItem value="price" className="h-6 px-2 text-xs">
            Price
          </ToggleGroupItem>
        </ToggleGroup>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6"
          disabled={lastText == null}
          onClick={() => {
            if (!lastText) return;
            if (draft.mode === "price") set({ price: lastText });
            else if (!draft.low.trim()) set({ low: lastText });
            else set({ high: lastText });
          }}
        >
          Use Last
        </Button>
      </div>
      {draft.mode === "price" ? (
        <CellInput label="Price" value={draft.price} placeholder="0.00" onChange={(price) => set({ price })} />
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <CellInput label="Low" value={draft.low} placeholder="0.00" onChange={(low) => set({ low })} />
          <CellInput label="High" value={draft.high} placeholder="0.00" onChange={(high) => set({ high })} />
        </div>
      )}
      {fieldNote("entry_low") || fieldNote("entry_high") ? (
        <p className="text-ask">{fieldNote("entry_low") || fieldNote("entry_high")}</p>
      ) : null}
      <CellInput label="Stop" value={draft.stop} placeholder="0.00" onChange={(stop) => set({ stop })} />
      {fieldNote("stop") ? <p className="text-ask">{fieldNote("stop")}</p> : null}
      <div className="flex flex-col gap-1">
        {draft.targets.map((target, index) => {
          const price = input.targets[index]?.price;
          const beside =
            target.mode === "r"
              ? price || ""
              : rAtPrice(read?.entry ?? "", input.stop, target.value) ?? "";
          return (
            <div key={index} className="flex items-center gap-1">
              <span className="w-6 font-mono text-muted-foreground">T{index + 1}</span>
              <ToggleGroup
                type="single"
                value={target.mode}
                onValueChange={(value) => {
                  if (value !== "price" && value !== "r") return;
                  const mode: "price" | "r" = value;
                  const next = draft.targets.map((row, i) => (i === index ? { ...row, mode, value: "" } : row));
                  set({ targets: next });
                }}
              >
                <ToggleGroupItem value="price" className="h-6 px-1.5 text-xs">
                  Price
                </ToggleGroupItem>
                <ToggleGroupItem value="r" className="h-6 px-1.5 text-xs">
                  R
                </ToggleGroupItem>
              </ToggleGroup>
              <Input
                aria-label={`T${index + 1}`}
                className="h-7"
                inputMode="decimal"
                value={target.value}
                onChange={(e) => {
                  const next = draft.targets.map((row, i) => (i === index ? { ...row, value: e.target.value } : row));
                  set({ targets: next });
                }}
              />
              <span className="w-16 truncate font-mono text-muted-foreground">{beside}</span>
              <Input
                aria-label={`T${index + 1} percent`}
                className="h-7 w-16"
                inputMode="decimal"
                placeholder="%"
                value={target.pct}
                onChange={(e) => {
                  const next = draft.targets.map((row, i) => (i === index ? { ...row, pct: e.target.value } : row));
                  set({ targets: next });
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6"
                aria-label={`Remove T${index + 1}`}
                onClick={() => set({ targets: draft.targets.filter((_, i) => i !== index) })}
              >
                ×
              </Button>
              {fieldNote(`targets.${index}`) ? <span className="text-ask">{fieldNote(`targets.${index}`)}</span> : null}
            </div>
          );
        })}
        {draft.targets.length < 4 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 self-start"
            onClick={() => set({ targets: [...draft.targets, { mode: "price", value: "", pct: "" }] })}
          >
            Add target
          </Button>
        ) : null}
        {fieldNote("targets") ? <p className="text-ask">{fieldNote("targets")}</p> : null}
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">Trigger</span>
        <Input
          value={draft.trigger}
          placeholder="What must happen before entering? e.g. 4h close above 2.30"
          onChange={(e) => set({ trigger: e.target.value })}
        />
      </label>
      {read ? (
        <p className="font-mono" title="Unallocated size counts as 0R">
          {`R ${read.r} (${read.rPct}%)`}
          {read.multiples.map((multiple, i) => (multiple ? ` · T${i + 1} ${multiple}R` : "")).join("")}
          {read.blended ? ` · blended ${read.blended}R` : ""}
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" className="h-7" disabled={issue != null || sending}>
          Save
        </Button>
        <Button type="button" variant="ghost" size="sm" className="h-7" onClick={() => setDraft(fromIdea(idea))}>
          Cancel
        </Button>
        {note ? <span className="text-muted-foreground">{note}</span> : null}
      </div>
    </form>
  );
}
