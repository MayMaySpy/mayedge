import { useState } from "react";
import { ChevronDown, Pin } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import {
  parseTimeframe,
  timeframeMenu,
  togglePin,
} from "@/lib/timeframe";

const HINT = "3m, 2h, 30s";

export function TimeframePins({
  timeframe,
  pins,
  onSelect,
  onPins,
}: {
  timeframe: string;
  pins: readonly string[];
  onSelect: (label: string) => void;
  onPins: (pins: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [pinFull, setPinFull] = useState(false);
  const unpinned = !pins.includes(timeframe);
  const groups = timeframeMenu(pins, timeframe);

  const pick = (label: string) => {
    onSelect(label);
    setOpen(false);
    setDraft("");
    setInvalid(false);
  };

  const pin = (label: string) => {
    const next = togglePin(pins, label);
    if (next.full) {
      setPinFull(true);
      return;
    }
    setPinFull(false);
    onPins(next.pins);
  };

  return (
    <div className="flex min-w-0 items-center">
      <div className="min-w-0 overflow-hidden">
        <ToggleGroup
          type="single"
          size="sm"
          spacing={0}
          value={unpinned ? "" : timeframe}
          onValueChange={(value) => {
            if (value) onSelect(value);
          }}
        >
          {pins.map((label) => (
            <ToggleGroupItem
              key={label}
              value={label}
              className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
            >
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) {
            setDraft("");
            setInvalid(false);
            setPinFull(false);
          }
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={unpinned ? timeframe : "Timeframes"}
            title="Timeframe"
            className={cn(
              "inline-flex h-5 shrink-0 items-center gap-px rounded-sm px-1 font-mono text-xs text-muted-foreground hover:bg-accent hover:text-foreground",
              unpinned && "bg-rule text-foreground"
            )}
          >
            {unpinned ? timeframe : null}
            <ChevronDown className="size-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" side="bottom" className="w-56 p-2">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const parsed = parseTimeframe(draft);
              if (!parsed) {
                setInvalid(true);
                return;
              }
              pick(parsed.label);
            }}
          >
            <Input
              value={draft}
              placeholder={HINT}
              aria-label="Timeframe"
              aria-invalid={invalid}
              autoFocus
              onChange={(event) => {
                setDraft(event.target.value);
                setInvalid(false);
              }}
            />
          </form>
          {invalid ? <p className="px-1.5 pt-1 text-sm text-muted-foreground">{HINT}</p> : null}
          {pinFull ? (
            <p className="px-1.5 pt-1 text-sm text-muted-foreground">Unpin one to pin another.</p>
          ) : null}
          <div className="max-h-80 overflow-y-auto">
            {groups.map((group) => (
              <div key={group.unit}>
                <div className="px-1.5 pt-2 pb-0.5 text-sm text-muted-foreground">{group.unit}</div>
                <ul>
                  {group.rows.map((row) => (
                    <li key={row.label} className="flex items-center">
                      <button
                        type="button"
                        className={cn(
                          "flex min-w-0 flex-1 items-center gap-2 rounded-sm px-1.5 py-1 text-left font-mono text-sm hover:bg-accent",
                          row.label === timeframe && "bg-rule"
                        )}
                        onClick={() => pick(row.label)}
                      >
                        <span>{row.label}</span>
                        {row.depth ? (
                          <span className="text-muted-foreground">{row.depth}</span>
                        ) : null}
                      </button>
                      <button
                        type="button"
                        aria-label={row.pinned ? `Unpin ${row.label}` : `Pin ${row.label}`}
                        title={pinFull && !row.pinned ? "Unpin one to pin another" : undefined}
                        className={cn(
                          "inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground",
                          row.pinned && "text-foreground"
                        )}
                        onClick={() => pin(row.label)}
                      >
                        <Pin className={cn("size-3", row.pinned && "fill-current")} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
