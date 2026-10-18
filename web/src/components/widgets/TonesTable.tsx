import { memo, useEffect, useMemo, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatClock } from "@/lib/alertFormat";
import { api } from "@/lib/api";
import { useToneBoard } from "@/lib/liveData";
import { notifyErr } from "@/lib/notify";
import { toneGrid } from "@/lib/scanActivity";
import {
  DEFAULT_TONE_TIMEFRAMES,
  TONE_TIMEFRAME_CAP,
  TONE_TIMEFRAME_CHOICES,
  toggleToneTimeframe,
} from "@/lib/toneTimeframes";
import { cn } from "@/lib/utils";

// The chart's own blue and orange.
const TONE_COLOR = { blue: "rgb(0, 102, 255)", orange: "rgb(255, 152, 0)" } as const;

interface TonesTableProps {
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const TonesTable = memo(function TonesTable({ symbol, onSymbolChange }: TonesTableProps) {
  const board = useToneBoard();
  const [timeframes, setTimeframes] = useState<readonly string[]>(DEFAULT_TONE_TIMEFRAMES);
  const [cap, setCap] = useState(TONE_TIMEFRAME_CAP);
  const [choices, setChoices] = useState<readonly string[]>(TONE_TIMEFRAME_CHOICES);
  const selected = symbol.toUpperCase();
  const grid = useMemo(() => toneGrid(board), [board]);

  useEffect(() => {
    let cancel = false;
    api
      .toneTimeframes()
      .then((row) => {
        if (cancel) return;
        setTimeframes(row.timeframes);
        setCap(row.cap);
        if (row.choices.length) setChoices(row.choices);
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, []);

  const toggle = (label: string) => {
    const next = toggleToneTimeframe(timeframes, label);
    if (next === timeframes) return;
    setTimeframes(next);
    api
      .setToneTimeframes([...next])
      .then((row) => setTimeframes(row.timeframes))
      .catch((err: unknown) => {
        setTimeframes(timeframes);
        notifyErr(err instanceof Error ? err.message : "Could not save timeframes");
      });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-rule px-2 py-1">
        <span className="mr-1 font-mono text-xs tracking-wide text-muted-foreground uppercase">
          Timeframes
        </span>
        {choices.map((label) => {
          const on = timeframes.includes(label);
          return (
            <Button
              key={label}
              type="button"
              size="sm"
              variant={on ? "default" : "outline"}
              aria-pressed={on}
              disabled={!on && timeframes.length >= cap}
              className="h-5 px-1.5 font-mono text-xs"
              onClick={() => toggle(label)}
            >
              {label}
            </Button>
          );
        })}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="h-8 hover:bg-transparent">
              <TableHead className="text-left font-mono text-xs tracking-wide uppercase">Market</TableHead>
              {timeframes.map((label) => (
                <TableHead key={label} className="text-right font-mono text-xs tracking-wide uppercase">
                  {label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {grid.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={timeframes.length + 1}
                  className="px-3 py-8 text-center text-muted-foreground"
                >
                  {timeframes.length === 0
                    ? "Pick a timeframe"
                    : "No liquid market closed its last bar blue or orange"}
                </TableCell>
              </TableRow>
            ) : (
              grid.map((row) => (
                <TableRow
                  key={row.marketIndex}
                  data-state={row.symbol.toUpperCase() === selected ? "selected" : undefined}
                  className="h-9 cursor-pointer tabular-nums"
                  onClick={() => onSymbolChange?.(row.symbol)}
                >
                  <TableCell>
                    <div className="flex min-w-0 items-center gap-2">
                      <TokenMark symbol={row.symbol} />
                      <span className="font-sans text-lg text-text">{row.symbol}</span>
                    </div>
                  </TableCell>
                  {timeframes.map((label) => {
                    const cell = row.cells[label];
                    return (
                      <TableCell key={label} className={cn("text-right", !cell && "text-muted-foreground")}>
                        {cell ? (
                          <>
                            <span style={{ color: TONE_COLOR[cell.tone] }} className="capitalize">
                              {cell.tone}
                            </span>
                            <span className="ml-1.5 text-muted-foreground">
                              {formatClock(cell.closedAt)}
                            </span>
                          </>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
});
