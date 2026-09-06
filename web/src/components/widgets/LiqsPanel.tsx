import { memo, useMemo, useState } from "react";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { HeaderNumberInput } from "@/components/desk/HeaderNumberInput";
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
import { useLiveLiquidations, type LiquidationEvent } from "@/lib/liveData";
import { liqIdentity, pairLabel } from "@/lib/venuePair";
import { cn, formatPrice, formatSize } from "@/lib/utils";

const MIN_USD_KEY = "mayedge-liqs-min-usd";
const DEFAULT_MIN_USD = 1000;
const MAX_ROWS = 80;

function loadMinUsd(): number {
  try {
    const n = parseFloat(localStorage.getItem(MIN_USD_KEY) ?? "");
    return Number.isFinite(n) && n >= 0 ? n : DEFAULT_MIN_USD;
  } catch {
    return DEFAULT_MIN_USD;
  }
}

function usdOf(l: LiquidationEvent): number {
  const u = parseFloat(l.usd_amount ?? "");
  if (Number.isFinite(u) && u > 0) return u;
  const px = parseFloat(l.price);
  const sz = parseFloat(l.size);
  if (Number.isFinite(px) && Number.isFinite(sz)) return px * sz;
  return 0;
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

interface LiqsPanelProps {
  onOpenPair?: (symbol: string) => void;
  onClose?: () => void;
}

export const LiqsPanel = memo(function LiqsPanel({ onOpenPair, onClose }: LiqsPanelProps) {
  const all = useLiveLiquidations();
  const [minUsd, setMinUsd] = useState(loadMinUsd);

  const rows = useMemo(
    () => all.filter((l) => usdOf(l) >= minUsd).slice(0, MAX_ROWS),
    [all, minUsd]
  );

  const setMin = (raw: string) => {
    const n = parseFloat(raw);
    const next = Number.isFinite(n) && n >= 0 ? n : 0;
    setMinUsd(next);
    try {
      localStorage.setItem(MIN_USD_KEY, String(next));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader
        title="Liqs"
        onClose={onClose}
        trailing={
          <Field orientation="horizontal" className="w-auto items-center gap-1.5">
            <FieldLabel htmlFor="liqs-min-usd" className="font-mono text-[10px] text-muted">
              ≥$
            </FieldLabel>
            <HeaderNumberInput
              id="liqs-min-usd"
              min={0}
              step={100}
              value={minUsd}
              widthClass="w-[4.75rem] text-right"
              onChange={(n) => setMin(String(n))}
            />
          </Field>
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
                const usd = usdOf(l);
                const kind = l.kind === "deleverage" ? "ADL" : "LIQ";
                return (
                  <TableRow
                    key={liqIdentity(l.trade_id)}
                    className="cursor-pointer"
                    title={`${kind} ${pairLabel(l.symbol)}`}
                    onClick={() => onOpenPair?.(l.symbol)}
                  >
                    <TableCell className="text-muted">{formatTime(l.timestamp)}</TableCell>
                    <TableCell className={cn(l.side === "buy" ? "text-bid" : "text-ask")}>
                      {pairLabel(l.symbol)}
                    </TableCell>
                    <TableCell className="text-muted">{kind}</TableCell>
                    <TableCell className="text-right text-muted">
                      {formatSize(l.size)}
                    </TableCell>
                    <TableCell className="text-right">{formatPrice(l.price)}</TableCell>
                    <TableCell className="text-right text-muted">{formatUsd(usd)}</TableCell>
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
