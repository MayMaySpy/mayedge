import { memo, useMemo, useState } from "react";
import { FilterPopover } from "@/components/desk/FilterPopover";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { HeaderNumberInput } from "@/components/desk/HeaderNumberInput";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
  type RowAccent,
} from "@/components/ui/table";
import { isSignificantLiq, liqUsd } from "@/lib/liqs";
import { useLiveLiquidations, type LiquidationEvent } from "@/lib/liveData";
import { liqIdentity, pairLabel } from "@/lib/venuePair";
import { cn, formatSize, formatUsdCompact } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";
import { utcClock } from "@/lib/utcTime";

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
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return formatUsdCompact(n);
}

function sigAccent(l: LiquidationEvent, tint: boolean): RowAccent | null {
  if (!tint) return null;
  if (l.side === "buy") return "bid";
  if (l.side === "sell") return "ask";
  return "warn";
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
          <FilterPopover>
            <FieldGroup className="gap-3">
              <Field>
                <FieldLabel htmlFor="liqs-min-usd">Min USD</FieldLabel>
                <HeaderNumberInput
                  id="liqs-min-usd"
                  min={0}
                  step={100}
                  value={minUsd}
                  widthClass="w-full text-right"
                  onChange={(n) => {
                    setMinUsd(n);
                    persist(MIN_USD_KEY, String(n));
                  }}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="liqs-sig-usd">Significant USD</FieldLabel>
                <HeaderNumberInput
                  id="liqs-sig-usd"
                  min={0}
                  step={1000}
                  value={sigUsd}
                  widthClass="w-full text-right"
                  onChange={(n) => {
                    setSigUsd(n);
                    persist(SIG_USD_KEY, String(n));
                  }}
                />
              </Field>
              <Field orientation="horizontal" className="items-center justify-between">
                <FieldLabel htmlFor="liqs-sig-color">Color significant</FieldLabel>
                <Switch
                  id="liqs-sig-color"
                  checked={sigColor}
                  onCheckedChange={(on) => {
                    setSigColor(on);
                    persist(SIG_COLOR_KEY, on ? "1" : "0");
                  }}
                />
              </Field>
            </FieldGroup>
          </FilterPopover>
        }
      />

      <ScrollArea className="min-h-0 flex-1">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="hover:bg-transparent">
              <TableHead hideBelow="2xs" className="pl-2.5">Time (UTC)</TableHead>
              <TableHead>Pair</TableHead>
              <TableHead hideBelow="md">Kind</TableHead>
              <TableHead hideBelow="sm" className="text-right">Size</TableHead>
              <TableHead className="text-right">Px</TableHead>
              <TableHead className="text-right">USD</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={6} className="h-16 p-0">
                  <Empty>
                    <EmptyHeader>
                      <EmptyTitle>No liquidations</EmptyTitle>
                      <EmptyDescription>Waiting for fills above the min size</EmptyDescription>
                    </EmptyHeader>
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
                    accent={sigAccent(l, tint)}
                    className="cursor-pointer"
                    title={`${kind} ${pairLabel(l.symbol)}${l.fill_count != null && l.fill_count > 1 ? ` · ${l.fill_count} fills` : ""}${significant ? " · significant" : ""}`}
                    onClick={() => onOpenPair?.(l.symbol)}
                  >
                    <TableCell hideBelow="2xs" className="pl-2.5 text-muted-foreground">{utcClock(l.timestamp)}</TableCell>
                    <TableCell>
                      <TableName className={l.side === "buy" ? "text-bid" : "text-ask"}>
                        {pairLabel(l.symbol)}
                      </TableName>
                    </TableCell>
                    <TableCell hideBelow="md" className="text-muted-foreground">{kind}</TableCell>
                    <TableCell hideBelow="sm" className="text-right text-muted-foreground">
                      {formatSize(l.size)}
                      {l.fill_count != null && l.fill_count > 1 ? (
                        <span className="ml-1 text-xs">×{l.fill_count}</span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right">{marketPrice(l.price, l.symbol)}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right",
                        tint ? (l.side === "buy" ? "text-bid" : "text-ask") : "text-muted-foreground"
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
