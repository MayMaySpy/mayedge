import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  type AutoscaleInfoProvider,
  ColorType,
  createChart,
  LineSeries,
  type MouseEventParams,
  type UTCTimestamp,
} from "lightweight-charts";
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
import type { PortfolioDay, PortfolioHistory, PortfolioKind, PortfolioMargin, PortfolioNow } from "@/lib/api";
import { magnitude, money, pctPoints, pnlClass, price, size } from "@/lib/journalFormat";
import {
  type FlowEvent,
  flowEvents,
  PORTFOLIO_KIND_COLORS,
  PORTFOLIO_KIND_LABELS,
  PORTFOLIO_KINDS,
} from "@/lib/portfolioDay";
import { pageOf } from "@/lib/portfolioShare";
import { theme } from "@/lib/theme";
import { DESK_DATE_LOCALE } from "@/lib/utcTime";
import { cn, formatNumber } from "@/lib/utils";

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
  return Number.isFinite(n) ? `${formatNumber(n, 2)}%` : "—";
}

/** Token amounts behind a share, to the cent's worth of precision: 1,018.21. */
function units(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? formatNumber(n, 2) : "—";
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

/** Every time on the page is UTC, and says so (W2). */
function when(ts: number, hourly: boolean): string {
  const text = new Date(ts).toLocaleString(DESK_DATE_LOCALE, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(hourly ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}),
  });
  return hourly ? `${text} UTC` : text;
}

/** The value axis in whole dollars, short: $800, $8k, $12.5k. */
function axisUsd(value: number): string {
  const abs = Math.abs(value);
  const text =
    abs >= 1000
      ? `${formatNumber(abs / 1000, 0, 1)}k`
      : formatNumber(abs, 0);
  return `${value < 0 ? "-" : ""}$${text}`;
}

const FLOW_GLYPHS = { move: "⇄", in: "↑", out: "↓" } as const;

/** W4: one chip per moment money moved, under the plot at that moment's x. Hover or focus says what moved. */
function FlowLane({ events }: { events: (FlowEvent & { x: number })[] }) {
  return (
    <div className="relative h-6" aria-label="Flows">
      {events.map((e) => (
        <Tooltip key={e.ts}>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={e.label}
              className="absolute top-0.5 flex size-5 -translate-x-1/2 items-center justify-center rounded-full border bg-panel text-xs leading-none text-text outline-none focus-visible:ring-1 focus-visible:ring-ring"
              style={{ left: e.x, borderColor: e.color }}
            >
              {FLOW_GLYPHS[e.kind]}
            </button>
          </TooltipTrigger>
          <TooltipContent className="font-mono tabular-nums">{e.label}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}

/** W4: each kind's value over time, the total, and where money moved in or out. `height="fill"` takes its flex parent's height. */
export function ValueChart({
  history,
  kinds,
  height = 260,
}: {
  history: PortfolioHistory;
  kinds: PortfolioKind[];
  height?: number | "fill";
}) {
  const fill = height === "fill";
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const points = history.points;
  const hourly = history.resolution === "1h";
  const index = useMemo(() => new Map(points.map((p, i) => [Math.floor(p.ts / 1000), i])), [points]);
  const events = useMemo(() => flowEvents(history.flows), [history.flows]);
  const [placed, setPlaced] = useState<(FlowEvent & { x: number })[]>([]);

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;
    const chart = createChart(el, {
      ...(fill ? {} : { height }),
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: theme.muted,
        fontFamily: theme.fontMono,
        fontSize: theme.chartFontSize,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.rule } },
      localization: { locale: theme.chartLocale, priceFormatter: axisUsd },
      // Zero sits on the bottom edge: no margin below it to draw negative ticks into.
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0 } },
      timeScale: { borderVisible: false, timeVisible: hourly },
      handleScroll: false,
      handleScale: false,
    });
    const at = (ts: number) => Math.floor(ts / 1000) as UTCTimestamp;
    // Values are never below zero; without this the scale pads down past it.
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
    }
    chart.timeScale().fitContent();
    // Flows sit in their own lane under the plot, at the x of their bucket: never on a line.
    let frame = 0;
    const place = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() =>
        setPlaced(
          events.flatMap((e) => {
            const x = index.has(Math.floor(e.ts / 1000)) ? chart.timeScale().timeToCoordinate(at(e.ts)) : null;
            return x == null ? [] : [{ ...e, x }];
          }),
        ),
      );
    };
    place();
    chart.timeScale().subscribeSizeChange(place);
    const onMove = (param: MouseEventParams) => {
      const time = typeof param.time === "number" ? param.time : null;
      setHover(time == null ? null : (index.get(time) ?? null));
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      cancelAnimationFrame(frame);
      chart.timeScale().unsubscribeSizeChange(place);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [events, fill, height, hourly, index, kinds, points]);

  if (points.length === 0) {
    return <div className="px-2 py-6 text-muted-foreground">No history stored yet. The desk fills it within a few minutes.</div>;
  }
  const at = hover ?? points.length - 1;
  const point = points[at];
  const moment = events.find((e) => e.ts === point.ts);
  return (
    <div className={cn("flex flex-col gap-1", fill && "min-h-0 flex-1")}>
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
        {moment ? <span className="text-muted-foreground">{moment.label}</span> : null}
      </div>
      <div className={cn("relative", fill && "min-h-0 flex-1")}>
        <div ref={ref} className="h-full w-full" style={fill ? undefined : { height }} />
        {placed.map((e) => (
          <div
            key={`guide-${e.ts}`}
            aria-hidden
            className="pointer-events-none absolute inset-y-0 border-l border-dashed border-muted-foreground/35"
            style={{ left: e.x }}
          />
        ))}
      </div>
      {placed.length > 0 ? <FlowLane events={placed} /> : null}
    </div>
  );
}

/** W7: a page before the table can measure itself, and the fewest rows a page ever holds. */
const DAYS_PER_PAGE = 20;
const MIN_DAYS_PER_PAGE = 5;

/**
 * W7: as many rows as fit the table's height, measured from its header and a row, and
 * measured again whenever the table resizes.
 */
function useRowsThatFit(box: React.RefObject<HTMLDivElement | null>, hasRows: boolean): number {
  const [fit, setFit] = useState(DAYS_PER_PAGE);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || !hasRows) return;
    const measure = () => {
      const head = el.querySelector("thead")?.getBoundingClientRect().height ?? 0;
      const row = el.querySelector("tbody tr")?.getBoundingClientRect().height ?? 0;
      if (row > 0 && el.clientHeight > 0) {
        setFit(Math.max(MIN_DAYS_PER_PAGE, Math.floor((el.clientHeight - head) / row)));
      }
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [box, hasRows]);
  return fit;
}

/** W5, W7: the days newest first, a page at a time. */
export function DaysTable({ days, kinds }: { days: PortfolioDay[]; kinds: PortfolioKind[] }) {
  const box = useRef<HTMLDivElement>(null);
  // The newest day shown, not a page number, so a resize keeps that day in view.
  const [first, setFirst] = useState(0);
  const all = useMemo(() => [...days].reverse(), [days]);
  const perPage = useRowsThatFit(box, all.length > 0);
  const { rows, page, pages } = pageOf(all, Math.floor(first / perPage), perPage);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1">
      <div ref={box} className="min-h-0 flex-1 overflow-y-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-panel">
            <TableRow>
              <TableHead>Day (UTC)</TableHead>
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
              <TableRow key={day.day}>
                <TableCell>{day.day}</TableCell>
                {kinds.map((k) => (
                  <TableCell key={k} className={cn("text-right", pnlClass(day.kinds[k]))}>
                    {money(day.kinds[k])}
                  </TableCell>
                ))}
                <TableCell className={cn("text-right", pnlClass(day.total))}>{money(day.total)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {pages > 1 ? (
        <div className="flex items-center justify-end gap-2 px-2 text-muted-foreground">
          <span className="font-mono tabular-nums">
            {page * perPage + 1}–{page * perPage + rows.length} of {all.length}
          </span>
          <Button type="button" variant="ghost" size="sm" className="h-6 px-2" disabled={page === 0} onClick={() => setFirst((page - 1) * perPage)}>
            Newer
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            disabled={page >= pages - 1}
            onClick={() => setFirst((page + 1) * perPage)}
          >
            Older
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** W6: one Holding, its header the kind's key, value, share of the total and change since the open. */
function HoldingCard({ kind, now, children }: { kind: PortfolioKind; now: PortfolioNow; children: React.ReactNode }) {
  const held = now.kinds[kind];
  const total = num(now.total.value);
  const share = total > 0 ? (num(held.value) / total) * 100 : 0;
  return (
    <section className="panel flex min-w-0 shrink-0 flex-col gap-1 p-1">
      <header className="flex items-center gap-2 px-2 pt-1">
        <LineKey kind={kind} />
        <h2>{PORTFOLIO_KIND_LABELS[kind]}</h2>
        <span className="ml-auto font-mono tabular-nums">{usd(held.value)}</span>
        <span className="w-9 text-right font-mono tabular-nums text-muted-foreground">{share.toFixed(0)}%</span>
        <span
          className={cn("w-20 text-right font-mono tabular-nums", pnlClass(held.change))}
          title="Change since the open"
        >
          {money(held.change)}
        </span>
      </header>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

function Empty({ cols, children }: { cols: number; children: React.ReactNode }) {
  return (
    <TableRow>
      <TableCell colSpan={cols} className="text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

/** N10: the Portfolio margin, buying power beside the Perps value and never added to it. */
function MarginLine({ margin }: { margin: PortfolioMargin }) {
  return (
    <div
      className="mx-2 mt-1 border-t border-rule pt-1.5 text-muted-foreground"
      title="Buying power: USDC with the open uPnL, plus each collateral asset at its LTV. Not part of any value."
    >
      <div className="flex items-baseline gap-2">
        <span className="text-foreground">Portfolio margin</span>
        <span className="text-xs">buying power, not value</span>
        <span className="ml-auto font-mono tabular-nums text-foreground">{usd(margin.total)}</span>
      </div>
      {margin.parts.map((part) => (
        <div key={part.symbol + (part.cross ? ":cross" : "")} className="flex items-baseline gap-2 font-mono tabular-nums">
          <span>{part.cross ? `${part.symbol} and open uPnL` : part.symbol}</span>
          {!part.cross ? (
            <span className="text-xs">
              {size(part.qty)} × {price(part.price)} × {ltvPct(part.ltv)} LTV
            </span>
          ) : null}
          <span className="ml-auto">{usd(part.value)}</span>
        </div>
      ))}
    </div>
  );
}

function ltvPct(ltv: string | null): string {
  const n = Number(ltv);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : "—";
}

/** W6: what each Holding is made of, in the Allocation's order. */
export function Holdings({ now, className }: { now: PortfolioNow; className?: string }) {
  const staking = now.pools.filter((p) => p.kind === "staking");
  const llp = now.pools.filter((p) => p.kind === "llp");
  return (
    <div className={cn("flex min-h-0 flex-col gap-3", className)}>
      <HoldingCard kind="perps" now={now}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Asset</TableHead>
              <TableHead hideBelow="xs" className="text-right">Qty</TableHead>
              <TableHead className="text-right">Value</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {now.perps.collateral.map((row) => (
              <TableRow key={row.symbol}>
                <TableCell>
                  <TableName>{row.symbol}</TableName>
                  <span className="ml-1.5 text-muted-foreground">collateral</span>
                </TableCell>
                <TableCell hideBelow="xs" className="text-right">{size(row.qty)}</TableCell>
                <TableCell className="text-right">{usd(row.value)}</TableCell>
              </TableRow>
            ))}
            {now.perps.collateral.length === 0 ? <Empty cols={3}>No USDC collateral</Empty> : null}
            <TableRow>
              <TableCell>Open uPnL</TableCell>
              <TableCell hideBelow="xs" />
              <TableCell className={cn("text-right", pnlClass(now.perps.upnl))}>{money(now.perps.upnl)}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        {now.perps.margin ? <MarginLine margin={now.perps.margin} /> : null}
        <div className="flex items-center gap-2 px-2 py-1.5 text-muted-foreground">
          <a href="/journal" target="_blank" rel="noopener" className="ml-auto hover:text-foreground">
            Trades are in the Journal
          </a>
        </div>
      </HoldingCard>
      <HoldingCard kind="spot" now={now}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Asset</TableHead>
              <TableHead hideBelow="xs" className="text-right">Qty</TableHead>
              <TableHead hideBelow="sm" className="text-right">Price</TableHead>
              <TableHead className="text-right">Value</TableHead>
              <TableHead className="text-right">uPnL</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {now.spot.length === 0 ? (
              <Empty cols={5}>No spot holdings</Empty>
            ) : (
              now.spot.map((row) => (
                <TableRow key={row.symbol}>
                  <TableCell>
                    <TableName>{row.symbol}</TableName>
                  </TableCell>
                  <TableCell hideBelow="xs" className="text-right">{size(row.qty)}</TableCell>
                  <TableCell hideBelow="sm" className="text-right">{price(row.price)}</TableCell>
                  <TableCell className="text-right">{usd(row.value)}</TableCell>
                  <TableCell className={cn("text-right", pnlClass(row.upnl))}>
                    {row.upnl == null ? "—" : money(row.upnl)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        {now.spot_gap != null ? (
          <div className="px-2 py-1.5 text-warn" role="status">
            {usd(now.spot_gap)} of Spot is in no row above: the venue counts an asset the desk does not list.
          </div>
        ) : null}
      </HoldingCard>
      <HoldingCard kind="llp" now={now}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Shares</TableHead>
              <TableHead hideBelow="2xs" className="text-right">Put in</TableHead>
              <TableHead className="text-right">Value</TableHead>
              <TableHead className="text-right">APY</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {llp.length === 0 ? (
              <Empty cols={4}>Not in LLP</Empty>
            ) : (
              llp.map((row) => (
                <TableRow key={row.pool}>
                  <TableCell>{size(row.shares)}</TableCell>
                  <TableCell hideBelow="2xs" className="text-right">{usd(row.principal)}</TableCell>
                  <TableCell className="text-right">{usd(row.value)}</TableCell>
                  <TableCell className="text-right">{apy(row.apy)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </HoldingCard>
      <HoldingCard kind="staking" now={now}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Staked</TableHead>
              <TableHead hideBelow="2xs" className="text-right">Put in</TableHead>
              <TableHead className="text-right">Value</TableHead>
              <TableHead className="text-right">APY</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {staking.length === 0 ? (
              <Empty cols={4}>Nothing staked</Empty>
            ) : (
              staking.map((row) => (
                <TableRow key={row.pool}>
                  <TableCell>
                    {units(row.units)} {row.unit}
                  </TableCell>
                  <TableCell hideBelow="2xs" className="text-right">
                    {row.principal ? `${units(row.principal)} ${row.unit}` : "—"}
                  </TableCell>
                  <TableCell className="text-right">{usd(row.value)}</TableCell>
                  <TableCell className="text-right">{apy(row.apy)}</TableCell>
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
                  <TableCell>
                    {size(u.amount)} {ASSET_NAMES[u.asset_index] ?? `asset ${u.asset_index}`}
                  </TableCell>
                  <TableCell className="text-right">{when(u.unlock_ms, true)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </HoldingCard>
    </div>
  );
}
