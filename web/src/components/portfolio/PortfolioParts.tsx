import { useEffect, useMemo, useRef, useState } from "react";
import {
  type AutoscaleInfoProvider,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PortfolioDay, PortfolioHistory, PortfolioKind, PortfolioNow } from "@/lib/api";
import { magnitude, money, pctPoints, pnlClass, price, size } from "@/lib/journalFormat";
import { PORTFOLIO_KIND_COLORS, PORTFOLIO_KIND_LABELS, PORTFOLIO_KINDS } from "@/lib/portfolioDay";
import { theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const ASSET_NAMES: Record<number, string> = { 1: "ETH", 2: "LIT", 3: "USDC" };

function num(value: string | null | undefined): number {
  const n = Number(value ?? "0");
  return Number.isFinite(n) ? n : 0;
}

function usd(value: string | null | undefined): string {
  return value == null ? "—" : `$${magnitude(value)}`;
}

/** A yield or rate, no sign: 27.59%. */
function apy(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%` : "—";
}

/** Token amounts behind a share, to the cent's worth of precision: 1,018.21. */
function units(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}

function LineKey({ kind }: { kind: PortfolioKind | "total" }) {
  return (
    <span
      aria-hidden
      className="inline-block h-0.5 w-3 shrink-0 rounded-full"
      style={{ background: kind === "total" ? theme.text : PORTFOLIO_KIND_COLORS[kind] }}
    />
  );
}

/** W2: the total, and its change since the open. */
export function PortfolioHero({ now, spanLabel }: { now: PortfolioNow; spanLabel: string }) {
  const { total } = now;
  return (
    <div className="flex flex-wrap items-end gap-x-8 gap-y-2">
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground">Portfolio</span>
        <span className="text-[40px] font-medium leading-none">{usd(total.value)}</span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground">{spanLabel}</span>
        <span className="flex items-baseline gap-2">
          <span className={cn("text-2xl font-medium leading-none", pnlClass(total.change))}>{money(total.change)}</span>
          <span className={cn("font-mono tabular-nums", pnlClass(total.change))}>{pctPoints(total.change_pct)}</span>
        </span>
      </div>
      {num(total.flows) !== 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-muted-foreground">Flows, not counted as change</span>
          <span className="font-mono text-lg tabular-nums">{money(total.flows)}</span>
        </div>
      ) : null}
    </div>
  );
}

/** W3: part to whole, one bar, a 2px surface gap between kinds, labelled directly. */
export function AllocationBar({ now }: { now: PortfolioNow }) {
  const total = num(now.total.value);
  const parts = PORTFOLIO_KINDS.map((k) => ({ kind: k, value: num(now.kinds[k].value) })).filter((p) => p.value > 0);
  if (total <= 0 || parts.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-3 w-full gap-0.5 overflow-hidden" role="img" aria-label="Allocation by Holding">
        {parts.map((p, i) => (
          <div
            key={p.kind}
            title={`${PORTFOLIO_KIND_LABELS[p.kind]} ${usd(String(p.value))}`}
            className={cn(i === 0 && "rounded-l", i === parts.length - 1 && "rounded-r")}
            style={{ width: `${(p.value / total) * 100}%`, background: PORTFOLIO_KIND_COLORS[p.kind] }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        {parts.map((p) => (
          <span key={p.kind} className="inline-flex items-center gap-1.5">
            <LineKey kind={p.kind} />
            <span>{PORTFOLIO_KIND_LABELS[p.kind]}</span>
            <span className="font-mono tabular-nums">{usd(String(p.value))}</span>
            <span className="font-mono tabular-nums text-muted-foreground">
              {((p.value / total) * 100).toFixed(0)}%
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function when(ts: number, hourly: boolean): string {
  return new Date(ts).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    ...(hourly ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

/** W4: each kind's value over time, the total, and where money moved in or out. */
export function ValueChart({
  history,
  kinds,
  height = 260,
}: {
  history: PortfolioHistory;
  kinds: PortfolioKind[];
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const points = history.points;
  const hourly = history.resolution === "1h";
  const index = useMemo(() => new Map(points.map((p, i) => [Math.floor(p.ts / 1000), i])), [points]);

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;
    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: theme.muted,
        fontFamily: theme.fontMono,
        fontSize: theme.chartFontSize,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.rule } },
      // Zero sits on the bottom edge: no margin below it to draw negative ticks into.
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0 } },
      timeScale: { borderVisible: false, timeVisible: hourly },
      handleScroll: false,
      handleScale: false,
    });
    const at = (ts: number) => Math.floor(ts / 1000) as UTCTimestamp;
    // Values are never below zero; without this the scale pads down past it around the markers.
    const floorAtZero: AutoscaleInfoProvider = (base) => {
      const info = base();
      if (info?.priceRange) info.priceRange.minValue = Math.max(0, info.priceRange.minValue);
      return info;
    };
    const total = chart.addSeries(LineSeries, {
      color: theme.text,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: floorAtZero,
    });
    total.setData(points.map((p) => ({ time: at(p.ts), value: num(p.total) })));
    for (const kind of kinds) {
      const line = chart.addSeries(LineSeries, {
        color: PORTFOLIO_KIND_COLORS[kind],
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        autoscaleInfoProvider: floorAtZero,
      });
      line.setData(points.map((p) => ({ time: at(p.ts), value: num(p[kind]) })));
      const markers: SeriesMarker<Time>[] = history.flows
        .filter((f) => f.kind === kind && index.has(Math.floor(f.ts / 1000)))
        .map((f) => ({
          time: at(f.ts),
          // On the line itself: above or below it, the scale reserves room and pads past zero.
          position: "inBar",
          shape: num(f.amount) > 0 ? "arrowUp" : "arrowDown",
          color: PORTFOLIO_KIND_COLORS[kind],
          size: 1,
        }));
      if (markers.length) createSeriesMarkers(line, markers);
    }
    chart.timeScale().fitContent();
    const onMove = (param: MouseEventParams) => {
      const time = typeof param.time === "number" ? param.time : null;
      setHover(time == null ? null : (index.get(time) ?? null));
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [height, history.flows, hourly, index, kinds, points]);

  if (points.length === 0) {
    return <div className="px-2 py-6 text-muted-foreground">No history stored yet. The desk fills it within a few minutes.</div>;
  }
  const at = hover ?? points.length - 1;
  const point = points[at];
  const flows = history.flows.filter((f) => f.ts === point.ts);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 font-mono text-sm tabular-nums" aria-live="polite">
        <span className="text-muted-foreground">{when(point.ts, hourly)}</span>
        <span className="inline-flex items-center gap-1.5">
          <LineKey kind="total" />
          <span>{usd(point.total)}</span>
          <span className="text-muted-foreground">Total</span>
        </span>
        {kinds.map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <LineKey kind={k} />
            <span>{usd(point[k])}</span>
            <span className="text-muted-foreground">{PORTFOLIO_KIND_LABELS[k]}</span>
          </span>
        ))}
        {flows.map((f) => (
          <span key={f.kind} className="text-muted-foreground">
            {PORTFOLIO_KIND_LABELS[f.kind]} flow {money(f.amount)}
          </span>
        ))}
      </div>
      <div ref={ref} className="w-full" style={{ height }} />
    </div>
  );
}

/** W5: one day per row, each kind's Day change. The table behind the daily chart. */
export function DaysTable({ days, kinds }: { days: PortfolioDay[]; kinds: PortfolioKind[] }) {
  const rows = [...days].reverse();
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Day</TableHead>
            {kinds.map((k) => (
              <TableHead key={k} className="text-right">
                {PORTFOLIO_KIND_LABELS[k]}
              </TableHead>
            ))}
            <TableHead className="text-right">Total</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((day) => (
            <TableRow key={`${day.day}-${day.utc}`}>
              <TableCell className="font-mono" title={day.utc ? "A UTC day: older than the venue's hourly history" : undefined}>
                {day.day}
                {day.utc ? <span className="text-muted-foreground"> UTC</span> : null}
              </TableCell>
              {kinds.map((k) => (
                <TableCell key={k} className={cn("text-right font-mono tabular-nums", pnlClass(day.kinds[k]))}>
                  {money(day.kinds[k])}
                </TableCell>
              ))}
              <TableCell className={cn("text-right font-mono tabular-nums", pnlClass(day.total))}>{money(day.total)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-1 overflow-x-auto">
      <h2 className="px-2 text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

/** W6: what each Holding is made of. */
export function Holdings({ now }: { now: PortfolioNow }) {
  const perps = now.kinds.perps;
  const staking = now.pools.filter((p) => p.kind === "staking");
  const llp = now.pools.filter((p) => p.kind === "llp");
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="panel p-1">
        <Section title="Perps">
          <Table>
            <TableBody>
              <TableRow>
                <TableCell>Value (collateral and open uPnL)</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{usd(perps.value)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Change</TableCell>
                <TableCell className={cn("text-right font-mono tabular-nums", pnlClass(perps.change))}>
                  {money(perps.change)}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell colSpan={2}>
                  <a href="/journal" target="_blank" rel="noopener" className="text-muted-foreground hover:text-foreground">
                    Trades are in the Journal
                  </a>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Section>
      </div>
      <div className="panel p-1">
        <Section title="Spot">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Asset</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead className="text-right">uPnL</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {now.spot.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    No spot holdings
                  </TableCell>
                </TableRow>
              ) : (
                now.spot.map((row) => (
                  <TableRow key={row.symbol}>
                    <TableCell className="font-mono">{row.symbol}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{size(row.qty)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{price(row.price)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{usd(row.value)}</TableCell>
                    <TableCell className={cn("text-right font-mono tabular-nums", pnlClass(row.upnl))}>
                      {row.upnl == null ? "—" : money(row.upnl)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Section>
      </div>
      <div className="panel p-1">
        <Section title="Staking">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Staked</TableHead>
                <TableHead className="text-right">Put in</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead className="text-right">APY</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {staking.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    Nothing staked
                  </TableCell>
                </TableRow>
              ) : (
                staking.map((row) => (
                  <TableRow key={row.pool}>
                    <TableCell className="font-mono tabular-nums">
                      {units(row.units)} {row.unit}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {row.principal ? `${units(row.principal)} ${row.unit}` : "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{usd(row.value)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{apy(row.apy)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          {now.unlocks.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Unlocking</TableHead>
                  <TableHead className="text-right">Frees up</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {now.unlocks.map((u) => (
                  <TableRow key={`${u.asset_index}-${u.unlock_ms}`}>
                    <TableCell className="font-mono tabular-nums">
                      {size(u.amount)} {ASSET_NAMES[u.asset_index] ?? `asset ${u.asset_index}`}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{when(u.unlock_ms, true)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
        </Section>
      </div>
      <div className="panel p-1">
        <Section title="LLP">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Shares</TableHead>
                <TableHead className="text-right">Put in</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead className="text-right">APY</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {llp.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    Not in LLP
                  </TableCell>
                </TableRow>
              ) : (
                llp.map((row) => (
                  <TableRow key={row.pool}>
                    <TableCell className="font-mono tabular-nums">{size(row.shares)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{usd(row.principal)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{usd(row.value)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{apy(row.apy)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Section>
      </div>
    </div>
  );
}
