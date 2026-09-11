import { memo, useMemo, useState } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { HeaderNumberInput } from "@/components/desk/HeaderNumberInput";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { Field, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { isSignificantLiq, liqUsd } from "@/lib/liqs";
import { useLiveLiquidations, type LiquidationEvent } from "@/lib/liveData";
import { liqIdentity, pairLabel } from "@/lib/venuePair";
import { cn, formatPrice, formatSize } from "@/lib/utils";

const MIN_USD_KEY = "mayedge-liqs-min-usd";
const SIG_USD_KEY = "mayedge-liqs-sig-usd";
const SIG_COLOR_KEY = "mayedge-liqs-sig-color";
const DEFAULT_MIN_USD = 1000;
const DEFAULT_SIG_USD = 25_000;
const MAX_ROWS = 80;

function loadMinUsd(): number {
  try {
    const n = parseFloat(localStorage.getItem(MIN_USD_KEY) ?? "");
    return Number.isFinite(n) && n >= 0 ? n : DEFAULT_MIN_USD;
  } catch {
    return DEFAULT_MIN_USD;
  }
}

function loadSigUsd(): number {
  try {
    const n = parseFloat(localStorage.getItem(SIG_USD_KEY) ?? "");
    return Number.isFinite(n) && n >= 0 ? n : DEFAULT_SIG_USD;
  } catch {
    return DEFAULT_SIG_USD;
  }
}

function loadSigColor(): boolean {
  try {
    const raw = localStorage.getItem(SIG_COLOR_KEY);
    if (raw == null) return true;
    return raw !== "0";
  } catch {
    return true;
  }
}

function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

function formatUsd(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toFixed(0);
}

function formatTime(ts: number): string {
  if (!ts) return "—";
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function sigRowClass(l: LiquidationEvent, tint: boolean): string | undefined {
  if (!tint) return undefined;
  if (l.side === "buy") return "bg-bid/15";
  if (l.side === "sell") return "bg-ask/15";
  return "bg-warn/15";
}

interface LiqsPanelProps {
  onOpenPair?: (symbol: string) => void;
  onClose?: () => void;
}

export const LiqsPanel = memo(function LiqsPanel({ onOpenPair, onClose }: LiqsPanelProps) {
  const all = useLiveLiquidations();
  const [minUsd, setMinUsd] = useState(loadMinUsd);
  const [sigUsd, setSigUsd] = useState(loadSigUsd);
  const [sigColor, setSigColor] = useState(loadSigColor);

  const rows = useMemo(
    () => all.filter((l) => liqUsd(l) >= minUsd).slice(0, MAX_ROWS),
    [all, minUsd]
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader
        title="Liqs"
        onClose={onClose}
        trailing={
          <div className="flex items-center gap-2">
            <Field orientation="horizontal" className="w-auto items-center gap-1.5">
              <FieldLabel htmlFor="liqs-min-usd" className="font-mono text-[10px] text-muted">
                ≥$
              </FieldLabel>
              <HeaderNumberInput
                id="liqs-min-usd"
                min={0}
                step={100}
                value={minUsd}
                widthClass="w-[4.25rem] text-right"
                onChange={(n) => {
                  setMinUsd(n);
                  persist(MIN_USD_KEY, String(n));
                }}
              />
            </Field>
            <Field orientation="horizontal" className="w-auto items-center gap-1.5">
              <FieldLabel htmlFor="liqs-sig-usd" className="font-mono text-[10px] text-muted">
                sig
              </FieldLabel>
              <HeaderNumberInput
                id="liqs-sig-usd"
                min={0}
                step={1000}
                value={sigUsd}
                widthClass="w-[4.75rem] text-right"
                onChange={(n) => {
                  setSigUsd(n);
                  persist(SIG_USD_KEY, String(n));
                }}
              />
            </Field>
            <Field orientation="horizontal" className="w-auto items-center gap-1.5">
              <FieldLabel htmlFor="liqs-sig-color" className="font-mono text-[10px] text-muted">
                color
              </FieldLabel>
              <Switch
                id="liqs-sig-color"
                checked={sigColor}
                onCheckedChange={(on) => {
                  setSigColor(on);
                  persist(SIG_COLOR_KEY, on ? "1" : "0");
                }}
              />
            </Field>
          </div>
        }
      />

      <ScrollArea className="min-h-0 flex-1">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="hover:bg-transparent">
              <TableHead>Time</TableHead>
              <TableHead>Pair</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead className="text-right">Px</TableHead>
              <TableHead className="text-right">USD</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={6} className="h-16 p-0">
                  <Empty className="rounded-none border-0 py-4">
                    <EmptyDescription className="text-[11px] text-muted">Waiting…</EmptyDescription>
                  </Empty>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((l) => {
                const usd = liqUsd(l);
                const kind = l.kind === "deleverage" ? "ADL" : "LIQ";
                const significant = isSignificantLiq(usd, sigUsd);
                const tint = sigColor && significant;
                return (
                  <TableRow
                    key={liqIdentity(l.trade_id)}
                    className={cn("cursor-pointer", sigRowClass(l, tint))}
                    title={`${kind} ${pairLabel(l.symbol)}${l.fill_count != null && l.fill_count > 1 ? ` · ${l.fill_count} fills` : ""}${significant ? " · significant" : ""}`}
                    onClick={() => onOpenPair?.(l.symbol)}
                  >
                    <TableCell className="text-muted">{formatTime(l.timestamp)}</TableCell>
                    <TableCell className={cn(l.side === "buy" ? "text-bid" : "text-ask")}>
                      {pairLabel(l.symbol)}
                    </TableCell>
                    <TableCell className="text-muted">{kind}</TableCell>
                    <TableCell className="text-right text-muted">
                      {formatSize(l.size)}
                      {l.fill_count != null && l.fill_count > 1 ? (
                        <span className="ml-1 text-[10px]">×{l.fill_count}</span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right">{formatPrice(l.price)}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right",
                        tint ? (l.side === "buy" ? "text-bid" : "text-ask") : "text-muted"
                      )}
                    >
                      {formatUsd(usd)}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </ScrollArea>
    </div>
  );
});
