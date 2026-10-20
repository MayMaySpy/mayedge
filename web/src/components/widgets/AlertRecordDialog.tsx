import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  api,
  type AlertKnobSettings,
  type AlertRuleStats,
  type AlertWhatIf,
} from "@/lib/api";
import { ruleName } from "@/lib/alertFormat";
import { notifyErr } from "@/lib/notify";
import { cn } from "@/lib/utils";

const RANGES = ["7d", "30d", "90d"] as const;
const DAYS = { "7d": 7, "30d": 30, "90d": 90 } as const;
const GROUPS = [
  ["rule", "Rule"],
  ["rule_severity", "Rule · severity"],
  ["rule_direction", "Rule · direction"],
  ["held", "Held"],
  ["hour", "Hour"],
  ["symbol", "Market"],
] as const;

const FEW = 20;

function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

function share(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function StatPair({ label, base, next }: { label: string; base: string; next: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono tabular-nums">
        {base}
        <span className="text-muted-foreground"> → </span>
        {next}
      </span>
    </div>
  );
}

export function AlertRecordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("30d");
  const [by, setBy] = useState<string>("rule");
  const [rows, setRows] = useState<AlertRuleStats[]>([]);
  const [settings, setSettings] = useState<AlertKnobSettings | null>(null);
  const [rule, setRule] = useState("");
  const [knob, setKnob] = useState("");
  const [value, setValue] = useState("");
  const [whatIf, setWhatIf] = useState<AlertWhatIf | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const [record, knobs] = await Promise.all([
          api.alertStats(DAYS[range] * 24, by),
          api.alertSettings(),
        ]);
        if (cancelled) return;
        setRows(record.rules);
        setSettings(knobs);
      } catch (e) {
        if (!cancelled) notifyErr(e instanceof Error ? e.message : "Failed to load the record");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [by, open, range]);

  useEffect(() => {
    if (!settings || rule) return;
    const first = Object.keys(settings.by_rule)[0];
    const knobName = first ? settings.by_rule[first]?.[0] : "";
    if (!first || !knobName) return;
    setRule(first);
    setKnob(knobName);
    setValue(String(settings.knobs[knobName] ?? ""));
  }, [rule, settings]);

  useEffect(() => {
    if (!open || !rule || !knob || value === "") return;
    const number = Number(value);
    if (!Number.isFinite(number)) return;
    let cancelled = false;
    void api
      .alertWhatIf({ rule, knob, value: number, days: DAYS[range] })
      .then((out) => {
        if (!cancelled) setWhatIf(out);
      })
      .catch((e: unknown) => {
        if (!cancelled) notifyErr(e instanceof Error ? e.message : "What-if failed");
      });
    return () => {
      cancelled = true;
    };
  }, [knob, open, range, rule, value]);

  const knobsForRule = settings?.by_rule[rule] ?? [];

  const chooseRule = (next: string) => {
    setRule(next);
    const knobName = settings?.by_rule[next]?.[0] ?? "";
    setKnob(knobName);
    setValue(knobName && settings ? String(settings.knobs[knobName] ?? "") : "");
    setWhatIf(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Record</DialogTitle>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            type="single"
            size="sm"
            value={range}
            onValueChange={(next) => {
              if (next) setRange(next as (typeof RANGES)[number]);
            }}
          >
            {RANGES.map((item) => (
              <ToggleGroupItem key={item} value={item} className="h-6 px-2 text-xs">
                {item}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <select
            aria-label="Group"
            value={by}
            onChange={(e) => setBy(e.target.value)}
            className="h-6 rounded border border-border bg-transparent px-1 text-base"
          >
            {GROUPS.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="max-h-52 overflow-auto font-mono text-sm">
          <div className="grid grid-cols-[minmax(0,1fr)_2.5rem_3.5rem_3.5rem_3.5rem] gap-x-2 text-muted-foreground">
            <span />
            <span className="text-right">n</span>
            <span className="text-right">left</span>
            <span className="text-right">agst</span>
            <span className="text-right">left &gt;</span>
          </div>
          {rows.length === 0 ? (
            <p className="py-2 text-muted-foreground">No alerts in this range.</p>
          ) : (
            rows.map((row) => {
              const few = row.n < FEW;
              const label = by === "rule" ? ruleName(row.rule) : row.key || row.rule;
              return (
                <div
                  key={row.key || row.rule}
                  className="grid grid-cols-[minmax(0,1fr)_2.5rem_3.5rem_3.5rem_3.5rem] gap-x-2"
                >
                  <span className="truncate">
                    {label}
                    {few ? <span className="text-muted-foreground"> · too few rows</span> : null}
                  </span>
                  <span className="text-right text-muted-foreground">{row.n}</span>
                  <span className="text-right">{pct(row.left)}</span>
                  <span className="text-right">{pct(row.against)}</span>
                  <span
                    className={cn(
                      "text-right",
                      few
                        ? "text-muted-foreground"
                        : (row.left_beats ?? 0) >= 0.5
                          ? "text-bid"
                          : "text-ask",
                    )}
                  >
                    {share(row.left_beats)}
                  </span>
                </div>
              );
            })
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-rule pt-2">
          <select
            aria-label="Rule"
            value={rule}
            onChange={(e) => chooseRule(e.target.value)}
            className="h-6 rounded border border-border bg-transparent px-1 text-base"
          >
            {Object.keys(settings?.by_rule ?? {}).map((item) => (
              <option key={item} value={item}>
                {ruleName(item)}
              </option>
            ))}
          </select>
          <select
            aria-label="Knob"
            value={knob}
            onChange={(e) => {
              const next = e.target.value;
              setKnob(next);
              setValue(settings ? String(settings.knobs[next] ?? "") : "");
              setWhatIf(null);
            }}
            className="h-6 rounded border border-border bg-transparent px-1 text-base"
          >
            {knobsForRule.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <input
            aria-label="Knob value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="h-6 w-20 rounded border border-border bg-transparent px-1.5 font-mono"
          />
        </div>
        {whatIf ? (
          <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <StatPair label="n" base={String(whatIf.baseline.n)} next={String(whatIf.whatif.n)} />
            <StatPair label="Left" base={pct(whatIf.baseline.left)} next={pct(whatIf.whatif.left)} />
            <StatPair
              label="Against"
              base={pct(whatIf.baseline.against)}
              next={pct(whatIf.whatif.against)}
            />
            <StatPair
              label="Left > Against"
              base={share(whatIf.baseline.left_beats)}
              next={share(whatIf.whatif.left_beats)}
            />
          </div>
        ) : null}
        <p className="text-sm text-muted-foreground">Only tighter values can be tested.</p>
        {whatIf ? <pre className="font-mono text-sm text-muted-foreground">{whatIf.yaml}</pre> : null}
      </DialogContent>
    </Dialog>
  );
}
