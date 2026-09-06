import { memo, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { HeaderNumberInput } from "@/components/desk/HeaderNumberInput";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Field, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AlertEvent, AlertKind } from "@/lib/api";
import { useLiveAlerts } from "@/lib/liveData";
import { pairLabel } from "@/lib/venuePair";
import { cn } from "@/lib/utils";

const MIN_SEV_KEY = "mayedge-alerts-min-sev";
const DEFAULT_MIN_SEV = 2;
const MAX_ROWS = 80;
const TOAST_SEV = 3;
const TOAST_MAX = 2;
const TOAST_MAX_AGE_MS = 8_000;

const KIND_LABEL: Record<AlertKind, string> = {
  oi: "OI",
  volume: "Vol",
  spread: "Spread",
  price: "Price",
  premium: "Premium",
  dislocation: "Disloc",
  funding: "Funding",
  liq_cluster: "Liqs",
};

function loadMinSev(): number {
  try {
    const n = parseInt(localStorage.getItem(MIN_SEV_KEY) ?? "", 10);
    return Number.isFinite(n) && n >= 1 && n <= 3 ? n : DEFAULT_MIN_SEV;
  } catch {
    return DEFAULT_MIN_SEV;
  }
}

function eventMs(ts: number): number {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}

function formatTime(ts: number): string {
  if (!ts) return "—";
  return new Date(eventMs(ts)).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatValue(ev: AlertEvent): string {
  const v = ev.value;
  if (!Number.isFinite(v)) return "—";
  switch (ev.unit) {
    case "usd":
      if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
      if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(1)}k`;
      return `$${v.toFixed(0)}`;
    case "pct":
    case "pct_hr":
      return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
    case "bps":
      return `${v.toFixed(0)} bps`;
    default:
      return String(v);
  }
}

function severityClass(sev: number): string {
  if (sev >= 3) return "bg-loss/20 text-loss border-loss/30";
  if (sev >= 2) return "bg-warn/20 text-warn border-warn/30";
  return "bg-muted/30 text-muted border-rule";
}

interface AlertsPanelProps {
  onOpenPair?: (symbol: string) => void;
  onClose?: () => void;
}

export const AlertsPanel = memo(function AlertsPanel({
  onOpenPair,
  onClose,
}: AlertsPanelProps) {
  const all = useLiveAlerts();
  const [minSev, setMinSev] = useState(loadMinSev);
  const seenToastRef = useRef<Set<string>>(new Set());
  const mountedAtRef = useRef(Date.now());

  const rows = useMemo(
    () =>
      all
        .filter((e) => e.severity >= minSev)
        .sort((a, b) => (b.ts || 0) - (a.ts || 0))
        .slice(0, MAX_ROWS),
    [all, minSev]
  );

  useEffect(() => {
    const now = Date.now();
    let n = 0;
    for (const ev of all) {
      if (n >= TOAST_MAX) break;
      if (ev.severity < TOAST_SEV || seenToastRef.current.has(ev.id)) continue;
      const age = now - eventMs(ev.ts);
      if (age < 0 || age > TOAST_MAX_AGE_MS) continue;
      if (eventMs(ev.ts) < mountedAtRef.current - 1_000) continue;
      seenToastRef.current.add(ev.id);
      n += 1;
      toast(pairLabel(ev.symbol), {
        description: `${KIND_LABEL[ev.kind] ?? ev.kind}: ${ev.note}`,
        action: onOpenPair
          ? {
              label: "Open",
              onClick: () => onOpenPair(ev.symbol),
            }
          : undefined,
      });
    }
    if (seenToastRef.current.size > 400) {
      seenToastRef.current = new Set([...seenToastRef.current].slice(-200));
    }
  }, [all, onOpenPair]);

  const setMin = (raw: string) => {
    const n = parseInt(raw, 10);
    const next = Number.isFinite(n) && n >= 1 && n <= 3 ? n : DEFAULT_MIN_SEV;
    setMinSev(next);
    try {
      localStorage.setItem(MIN_SEV_KEY, String(next));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader
        title="Alerts"
        onClose={onClose}
        trailing={
          <Field orientation="horizontal" className="w-auto items-center gap-1.5">
            <FieldLabel htmlFor="alerts-min-sev" className="font-mono text-[10px] text-muted">
              sev≥
            </FieldLabel>
            <HeaderNumberInput
              id="alerts-min-sev"
              min={1}
              max={3}
              step={1}
              value={minSev}
              widthClass="w-7 text-center"
              onChange={(n) => setMin(String(n))}
            />
          </Field>
        }
      />
      <ScrollArea className="min-h-0 flex-1">
        {rows.length === 0 ? (
          <Empty className="py-8">
            <EmptyDescription>No alert signals yet</EmptyDescription>
          </Empty>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-panel">
              <TableRow className="hover:bg-transparent">
                <TableHead className="h-7 text-[10px]">Time</TableHead>
                <TableHead className="h-7 text-[10px]">Pair</TableHead>
                <TableHead className="h-7 text-[10px]">Kind</TableHead>
                <TableHead className="h-7 text-right text-[10px]">Mag</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((ev) => (
                <TableRow
                  key={ev.id}
                  className={cn(
                    "cursor-pointer text-xs",
                    onOpenPair && "hover:bg-accent/40"
                  )}
                  onClick={() => onOpenPair?.(ev.symbol)}
                  title={ev.note}
                >
                  <TableCell className="py-1 font-mono text-[10px] text-muted">
                    {formatTime(ev.ts)}
                  </TableCell>
                  <TableCell className="py-1 font-semibold">{pairLabel(ev.symbol)}</TableCell>
                  <TableCell className="py-1">
                    <Badge
                      variant={ev.severity >= 3 ? "ask" : ev.severity >= 2 ? "warn" : "muted"}
                      className={cn("h-5 rounded border px-1 font-normal", severityClass(ev.severity))}
                    >
                      {KIND_LABEL[ev.kind] ?? ev.kind}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1 text-right font-mono tabular-nums">
                    {formatValue(ev)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </ScrollArea>
    </div>
  );
});
