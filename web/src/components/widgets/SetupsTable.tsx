import { memo, useEffect, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
} from "@/components/ui/table";
import { formatClock } from "@/lib/alertFormat";
import { api, type SetupBoard } from "@/lib/api";
import { setupArrow, setupName } from "@/lib/setups";
import { cn } from "@/lib/utils";

// The board changes once an hour (setup-rules G2); a minute's poll is plenty.
const POLL_MS = 60_000;

interface SetupsTableProps {
  symbol: string;
  onSymbolChange?: (symbol: string) => void;
}

export const SetupsTable = memo(function SetupsTable({ symbol, onSymbolChange }: SetupsTableProps) {
  const [board, setBoard] = useState<SetupBoard | null>(null);
  const [failed, setFailed] = useState(false);
  const selected = symbol.toUpperCase();

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api
        .setups()
        .then((next) => {
          if (cancelled) return;
          setBoard(next);
          setFailed(false);
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const rows = board?.rows ?? [];
  const empty = failed
    ? "Couldn't load the Setups board"
    : board?.built_at == null
      ? "The board is built five minutes after the desk starts"
      : "No liquid perp is on a Setup this hour";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-rule px-2 py-1 text-xs text-muted-foreground">
        <span className="font-mono tracking-wide uppercase">Setups</span>
        <span>
          {board?.built_at != null ? `built ${formatClock(board.built_at)} UTC, hourly` : "not built yet"}
        </span>
        <span className="ml-auto">Listed, never raised</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow className="hover:bg-transparent">
              <TableHead>Market</TableHead>
              <TableHead>Setup</TableHead>
              <TableHead>What it shows</TableHead>
              <TableHead className="text-right" title="How many times its threshold it reached">
                Size
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                  {empty}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow
                  key={`${row.market_index}:${row.kind}`}
                  data-state={row.symbol.toUpperCase() === selected ? "selected" : undefined}
                  className="cursor-pointer"
                  onClick={() => onSymbolChange?.(row.symbol)}
                >
                  <TableCell>
                    <div className="flex min-w-0 items-center gap-2">
                      <TokenMark symbol={row.symbol} className="size-4" />
                      <TableName className="text-text">{row.symbol}</TableName>
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {setupName(row.kind)}
                    {setupArrow(row) ? (
                      <span
                        className={cn("ml-1", row.direction === "up" ? "text-bid" : "text-ask")}
                      >
                        {setupArrow(row)}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{row.note}</TableCell>
                  <TableCell className="text-right">{row.size.toFixed(1)}×</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
});
