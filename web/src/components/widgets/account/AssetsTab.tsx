import { useMemo, useState } from "react";
import { TokenMark } from "@/components/desk/TokenMark";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
  type HideBelow,
} from "@/components/ui/table";
import type { Asset, Market } from "@/lib/api";
import {
  assetChartSymbol,
  nextAssetSort,
  sortAssetRows,
  type AssetSort,
  type AssetSortKey,
} from "@/lib/assetsTable";
import { cn, formatPrice, formatSigned, formatSize, formatUsd } from "@/lib/utils";

function n(value: string | undefined) {
  const x = parseFloat(value ?? "");
  return Number.isFinite(x) ? x : 0;
}

function formatLtv(raw: string): string {
  const x = parseFloat(raw);
  if (!Number.isFinite(x) || x < 0) return "—";
  return `${(x * 100).toFixed(0)}%`;
}

function formatAssetUsd(value: number): string {
  if (!(value > 0)) return "—";
  return formatUsd(value);
}

function pnlClass(value: number) {
  if (value > 0) return "text-bid";
  if (value < 0) return "text-ask";
  return "text-muted-foreground";
}

function SortHead({
  label,
  column,
  sort,
  onSort,
  hideBelow,
}: {
  label: string;
  column: AssetSortKey;
  sort: AssetSort;
  onSort: (key: AssetSortKey) => void;
  hideBelow?: HideBelow;
}) {
  const active = sort.key === column;
  return (
    <TableHead hideBelow={hideBelow} className="text-right">
      <button
        type="button"
        title={`Sort by ${label}`}
        onClick={() => onSort(column)}
        className={cn(
          "ml-auto inline-flex items-center gap-0.5 hover:text-text",
          active && "text-text"
        )}
      >
        {label}
        {active ? (sort.dir === "desc" ? " ↓" : " ↑") : null}
      </button>
    </TableHead>
  );
}

export function AssetsTab({
  assets,
  markets,
  tradingEnabled,
  onSymbolChange,
}: {
  assets: Asset[];
  markets: Market[];
  tradingEnabled: boolean;
  onSymbolChange?: (symbol: string) => void;
}) {
  const [sort, setSort] = useState<AssetSort>({ key: "usd", dir: "desc" });
  const rows = useMemo(
    () =>
      sortAssetRows(
        assets.map((a) => ({ a, symbol: a.symbol, usd: n(a.usd), balance: n(a.balance) })),
        sort
      ),
    [assets, sort]
  );

  return (
    <ScrollArea className="h-full">
      {!rows.length ? (
        <Empty className="rounded-none border-0 p-6">
          <EmptyHeader>
            <EmptyTitle>No assets</EmptyTitle>
            <EmptyDescription>
              {tradingEnabled ? "Holdings will show here" : "Connect an API key to view assets"}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-2.5">Asset</TableHead>
              <SortHead
                label="Balance"
                column="balance"
                sort={sort}
                onSort={(key) => setSort((s) => nextAssetSort(s, key))}
              />
              <TableHead hideBelow="lg" className="text-right">Index</TableHead>
              <TableHead hideBelow="2xl" className="text-right">LTV</TableHead>
              <TableHead hideBelow="xl" className="text-right">Margin</TableHead>
              <TableHead hideBelow="xl" className="text-right">Available</TableHead>
              <TableHead hideBelow="sm" className="text-right">uPnL</TableHead>
              <SortHead
                label="USD"
                column="usd"
                sort={sort}
                onSort={(key) => setSort((s) => nextAssetSort(s, key))}
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(({ a }) => {
              const chart = assetChartSymbol(a.symbol, markets);
              const canSwitch = Boolean(chart && onSymbolChange);
              return (
                <TableRow
                  key={a.symbol}
                  onClick={
                    canSwitch && chart ? () => onSymbolChange?.(chart) : undefined
                  }
                  title={canSwitch && chart ? `Switch to ${chart}` : undefined}
                  className={cn(canSwitch && "cursor-pointer")}
                >
                  <TableCell className="pl-2.5">
                    <div className="flex min-w-0 items-center gap-2">
                      <TokenMark symbol={a.symbol} className="size-4" />
                      <TableName className="text-text">{a.symbol}</TableName>
                    </div>
                  </TableCell>
                  <TableCell className="text-right">{formatSize(a.balance)}</TableCell>
                  <TableCell hideBelow="lg" className="text-right">
                    {n(a.index_price) > 0 ? formatPrice(a.index_price) : "—"}
                  </TableCell>
                  <TableCell hideBelow="2xl" className="text-right">{formatLtv(a.ltv)}</TableCell>
                  <TableCell hideBelow="xl" className="text-right">
                    {formatSize(a.margin_balance)}
                  </TableCell>
                  <TableCell hideBelow="xl" className="text-right">{formatSize(a.available)}</TableCell>
                  <TableCell hideBelow="sm" className={cn("text-right", pnlClass(n(a.unrealized_pnl)))}>
                    {formatSigned(a.unrealized_pnl)}
                  </TableCell>
                  <TableCell className="text-right">{formatAssetUsd(n(a.usd))}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </ScrollArea>
  );
}
