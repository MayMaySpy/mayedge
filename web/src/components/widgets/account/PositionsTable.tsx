import { X } from "lucide-react";
import { PositionProtectPopover } from "@/components/widgets/PositionProtectPopover";
import { PositionPlanButton } from "@/components/widgets/planner/PositionPlanButton";
import { livePlannerFor } from "@/lib/plannerPlan";
import { liveTrailsFor } from "@/lib/trail";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableName,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SortHead } from "@/components/widgets/SortableHeads";
import { api, isLongPosition, type AlgoBook, type Market, type OpenOrder, type Position } from "@/lib/api";
import { useNextHour } from "@/hooks/useNextHour";
import { setAlgo, useLiveQuotes, type OpenTripRealized } from "@/lib/liveData";
import { formatFundingPct } from "@/lib/marketPicker";
import { utcClock } from "@/lib/utcTime";
import {
  equityShare,
  nextFunding,
  nextPosSort,
  realizedFor,
  realizedTitle,
  type PosSort,
} from "@/lib/positionsTable";
import { cn, formatPctAbs, formatSigned, formatSize, formatUsd, signClass } from "@/lib/utils";
import { marketPrice } from "@/lib/marketFormat";

function n(value: string | undefined) {
  const x = parseFloat(value ?? "");
  return Number.isFinite(x) ? x : 0;
}

function liqCushion(p: Position, mark: number): number | null {
  const liq = n(p.liquidation_price);
  const size = n(p.size);
  if (liq <= 0 || mark <= 0 || size === 0) return null;
  return size > 0 ? ((mark - liq) / mark) * 100 : ((liq - mark) / mark) * 100;
}

/** A Position as the table shows it: priced at the live mark. */
export interface LiveRow {
  p: Position;
  mark: number;
  pnl: number;
  marketIndex: number;
  sizeAbs: number;
  notional: number;
  roe: number | null;
}

interface PositionsTableProps {
  rows: LiveRow[];
  posSort: PosSort;
  setPosSort: (update: (s: PosSort) => PosSort) => void;
  market: Market | null;
  markets: Market[];
  algoBook: AlgoBook;
  journalOpen: OpenTripRealized[];
  /** The Portfolio margin, for each Position's share of it. */
  margin: number;
  orders: OpenOrder[];
  tradingEnabled: boolean;
  feedReady: boolean;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, ok: string) => Promise<boolean>;
  onCancel: (marketIndex: number, orderIndex: string | number) => Promise<void>;
  onClosePosition: (p: Position) => void;
  onSymbolChange?: (symbol: string) => void;
}

/** The Positions tab's table: one row per open Position, with its protect and close controls. */
export function PositionsTable({
  rows: sortedRows,
  posSort,
  setPosSort,
  market,
  markets,
  algoBook,
  journalOpen,
  margin,
  orders: allOrders,
  tradingEnabled,
  feedReady,
  busy,
  run,
  onCancel: cancelOrder,
  onClosePosition: closePosition,
  onSymbolChange,
}: PositionsTableProps) {
  const quotes = useLiveQuotes();
  const settleAt = useNextHour();
  return (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="pl-2.5">Market</TableHead>
                    <SortHead
                      label="Size"
                      column="size"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <SortHead
                      label="Notional"
                      column="notional"
                      hideBelow="xl"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <TableHead hideBelow="lg" className="text-right">Entry</TableHead>
                    <TableHead hideBelow="2xl" className="text-right">Liq</TableHead>
                    <SortHead
                      label="uPnL"
                      column="pnl"
                      sort={posSort}
                      onSort={(key) => setPosSort((s) => nextPosSort(s, key))}
                    />
                    <TableHead
                      hideBelow="lg"
                      className="text-right"
                      title="What this Position has closed since it opened, less fees. From the Journal, a few seconds behind a fill."
                    >
                      Realized
                    </TableHead>
                    <TableHead hideBelow="2xl" className="text-right">Funding</TableHead>
                    <TableHead
                      hideBelow="xl"
                      className="text-right"
                      title={`Next funding: what each Position receives or pays when the hour settles at ${utcClock(settleAt, false)} UTC, at the Funding estimate. It moves until then.`}
                    >
                      Next
                    </TableHead>
                    <TableHead hideBelow="sm" className="text-right">TP/SL</TableHead>
                    <TableHead className="text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedRows.map(({ p, mark, pnl, notional, roe }) => {
                    const long = isLongPosition(p);
                    const fund = n(p.funding_paid);
                    const realized = realizedFor(p, journalOpen);
                    const realizedNum = realized ? n(realized.realized) : 0;
                    const cushion = liqCushion(p, mark);
                    const liq = n(p.liquidation_price);
                    const m = markets.find((x) => x.market_index === p.market_index) ?? market;
                    const rate = quotes[p.market_index]?.funding_rate ?? m?.funding_rate ?? null;
                    const next = nextFunding(n(p.size), mark, rate);
                    const planner = livePlannerFor(algoBook, p.market_index);
                    const trails = liveTrailsFor(algoBook, p.market_index);
                    return (
                      <TableRow
                        key={p.market_index}
                        onClick={
                          onSymbolChange
                            ? () => {
                                if (market?.market_index !== p.market_index) onSymbolChange(p.symbol);
                              }
                            : undefined
                        }
                        title={onSymbolChange ? `Switch to ${p.symbol}` : undefined}
                        accent={long ? "bid" : "ask"}
                        className={cn(
                          market &&
                            p.market_index === market.market_index &&
                            "bg-elevated/35",
                          onSymbolChange && "cursor-pointer"
                        )}
                      >
                        <TableCell className="pl-2.5">
                          <TableName
                            className={cn(
                              long ? "text-bid" : "text-ask",
                              market?.market_index === p.market_index && "underline"
                            )}
                          >
                            {p.symbol}
                          </TableName>
                          <span className="ml-1.5 text-muted-foreground @max-lg/table:hidden">
                            {p.leverage}x {p.margin_mode}
                          </span>
                        </TableCell>
                        <TableCell className={cn("text-right", long ? "text-bid" : "text-ask")}>
                          {formatSize(Math.abs(n(p.size)))}
                        </TableCell>
                        <TableCell
                          hideBelow="xl"
                          className="text-right"
                          title={(() => {
                            const share = equityShare(notional, margin);
                            return share != null ? `${formatPctAbs(share)} of the Portfolio margin` : undefined;
                          })()}
                        >
                          {notional > 0 ? formatUsd(notional) : "—"}
                        </TableCell>
                        <TableCell hideBelow="lg" className="text-right">
                          {marketPrice(p.entry_price, p.symbol)}
                        </TableCell>
                        <TableCell hideBelow="2xl" className="text-right">
                          {liq > 0 ? marketPrice(p.liquidation_price, p.symbol) : "—"}
                          {cushion != null && (
                            <span
                              className={cn(
                                "ml-1 text-xs",
                                cushion < 8 ? "text-ask" : "text-muted-foreground"
                              )}
                            >
                              ({formatPctAbs(cushion)})
                            </span>
                          )}
                        </TableCell>
                        <TableCell className={cn("text-right font-medium", signClass(pnl))}>
                          {formatSigned(pnl)}
                          {roe != null && (
                            <span className="ml-1 text-xs font-normal">({formatPctAbs(roe)})</span>
                          )}
                        </TableCell>
                        <TableCell
                          hideBelow="lg"
                          className={cn("text-right", realized ? signClass(realizedNum) : "text-muted-foreground")}
                          title={realized ? realizedTitle(realized, (x) => formatSigned(x)) : "Not in the Journal yet"}
                        >
                          {realized ? (
                            <>
                              {realized.partial ? <span className="text-muted-foreground">~</span> : null}
                              {formatSigned(realizedNum)}
                            </>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell hideBelow="2xl" className={cn("text-right", signClass(fund))}>
                          {formatSigned(p.funding_paid)}
                        </TableCell>
                        <TableCell
                          hideBelow="xl"
                          className={cn("text-right", next != null ? signClass(next) : "text-muted-foreground")}
                          title={
                            next != null
                              ? `${formatFundingPct(rate)}/h at ${utcClock(settleAt, false)} UTC`
                              : "No funding estimate for this Market yet"
                          }
                        >
                          {next != null ? formatSigned(next) : "—"}
                        </TableCell>
                        <TableCell
                          hideBelow="sm"
                          className="text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="inline-flex items-center justify-end gap-1.5">
                            <PositionProtectPopover
                              lockedBy={planner ? "Planner" : null}
                              position={p}
                              mark={mark}
                              sizeDecimals={m?.size_decimals ?? 4}
                              priceDecimals={m?.price_decimals ?? 4}
                              tradingEnabled={tradingEnabled && feedReady}
                              busy={busy != null}
                              orders={allOrders}
                              onPlace={async (body) => {
                                const ok = await run(
                                  `protect-${p.market_index}`,
                                  () => api.placeStopTake(body),
                                  `${p.symbol} stop / take profit placed`
                                );
                                if (!ok) throw new Error("not placed");
                              }}
                              onCancel={async (orderIndex) => {
                                await cancelOrder(p.market_index, orderIndex);
                              }}
                              trails={trails}
                              onStartTrail={async (body) => {
                                const ok = await run(
                                  `trail-${p.market_index}`,
                                  async () => setAlgo(await api.algoStart("trail", body)),
                                  `${p.symbol} ${body.kind === "tp" ? "Trail Take Profit" : "Trail Stop"} started`
                                );
                                if (!ok) throw new Error("not started");
                              }}
                            />
                            <PositionPlanButton
                              position={p}
                              market={m ?? null}
                              running={planner}
                              disabled={!tradingEnabled || !feedReady || busy != null}
                            />
                          </div>
                        </TableCell>
                        <TableCell
                          className="pl-2 text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                type="button"
                                variant="danger"
                                size="icon"
                                disabled={!tradingEnabled || busy != null}
                                onClick={() => closePosition(p)}
                                className="size-6"
                              >
                                <X strokeWidth={2.25} />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Close {p.symbol}</TooltipContent>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
  );
}
