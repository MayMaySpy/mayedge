import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { BookOpen, LayoutGrid, Star, Wallet } from "lucide-react";
import { notifyErr, notifyOk, notifyWarn } from "@/lib/notify";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PortfolioToday } from "@/components/widgets/PortfolioToday";
import { FavoritesBar } from "@/components/widgets/FavoritesBar";
import { MarketPicker } from "@/components/widgets/MarketPicker";
import type { FundingAverage, Market } from "@/lib/api";
import { preferPerpMarket, algoBlotter, algoIsWorking } from "@/lib/algos";
import { api } from "@/lib/api";
import { useFavorites } from "@/lib/favorites";
import { pushRecent } from "@/lib/recents";
import {
  useAutoKill,
  useFeedHealth,
  useLiveAccount,
  useLiveAlgos,
  useLiveBbo,
  useLiveQuotes,
  overlayQuote,
  setAlgo,
} from "@/lib/liveData";
import { AutoKillSection } from "@/components/widgets/AutoKillSection";
import { cn, formatApr, formatPct, formatPrice, formatUsdCompact } from "@/lib/utils";
import { formatFundingPct } from "@/lib/marketPicker";
import { averageReading, headlineAverage } from "@/lib/funding";
import { formatClock } from "@/lib/alertFormat";
import { JOURNAL_PATH, PORTFOLIO_PATH } from "@/lib/deskRoute";

/** Prints settle hourly; a slow refresh keeps the average current. */
const FUNDING_AVERAGE_REFRESH_MS = 10 * 60_000;

interface HeaderProps {
  markets: Market[];
  symbol: string;
  onSymbolChange: (symbol: string) => void;
  network: string;
  connected: boolean;
  tradingEnabled: boolean;
  editing: boolean;
  onEditToggle: () => void;
  onResetLayout: () => void;
}

function formatOi(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value < 0) return "—";
  return formatUsdCompact(value) || "$0";
}

function HeaderStat({
  label,
  value,
  valueClass,
  hint,
  hintClass,
  aside,
  title,
  loud,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
  hintClass?: string;
  aside?: ReactNode;
  title?: string;
  loud?: boolean;
}) {
  const body = (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-xs uppercase tracking-[0.06em] text-muted-foreground">{label}</span>
      <span
        className={cn(
          "font-mono tabular-nums text-foreground",
          loud ? "text-xl font-medium leading-none" : "text-lg",
          valueClass
        )}
      >
        {value}
      </span>
      {hint ? (
        <span className={cn("font-mono text-sm tabular-nums text-muted-foreground", hintClass)}>
          {hint}
        </span>
      ) : null}
      {aside}
    </span>
  );
  if (!title) return body;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex cursor-default rounded-lg outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {body}
        </button>
      </TooltipTrigger>
      <TooltipContent>{title}</TooltipContent>
    </Tooltip>
  );
}

function StatRule() {
  return <Separator orientation="vertical" className="h-4 self-center" />;
}

function HeaderFavorite({ symbol }: { symbol: string }) {
  const [favorites, toggleFavorite] = useFavorites();
  if (!symbol) return null;
  const pinned = favorites.includes(symbol);
  const label = pinned ? `Unpin ${symbol}` : `Pin ${symbol}`;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={label}
          aria-pressed={pinned}
          className={cn("size-8", pinned && "text-warn hover:text-warn")}
          onClick={() => toggleFavorite(symbol)}
        >
          <Star className={cn(pinned && "fill-warn")} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function fundingTooltip(
  rate: number | null,
  apr: number | null,
  avg: FundingAverage | null
): string | undefined {
  if (rate == null) return undefined;
  const parts = [`${formatFundingPct(rate)} per hour`, `${formatFundingPct(rate * 8)} / 8h`];
  if (apr != null && apr > 0) parts.push("longs pay shorts");
  else if (apr != null && apr < 0) parts.push("shorts pay longs");
  if (apr != null) parts.push(`${formatApr(apr)} APR`);
  const means = (avg?.windows ?? [])
    .map((w) => {
      const read = averageReading(w);
      return read ? `${read.label} ${formatApr(read.apr)}` : null;
    })
    .filter((part): part is string => part != null);
  if (means.length) parts.push(`Settled average APR: ${means.join(", ")}`);
  const venueDays = avg?.windows[avg.windows.length - 1]?.venue_days ?? 0;
  if (means.length && venueDays > 0) parts.push(`${venueDays} days from Lighter's daily history`);
  return parts.join(". ");
}

function FundingAverageAside({ avg }: { avg: FundingAverage | null }) {
  const read = headlineAverage(avg);
  if (!read) return null;
  return (
    // Below xl the header has no room; the averages stay in the tooltip.
    <span className="hidden items-baseline gap-1 font-mono text-sm tabular-nums text-muted-foreground xl:inline-flex">
      <span aria-hidden>·</span>
      <span>{read.label}</span>
      <span className={read.apr > 0 ? "text-ask/80" : read.apr < 0 ? "text-bid/80" : undefined}>
        {formatApr(read.apr)}
      </span>
    </span>
  );
}

function useFundingAverage(symbol: string, perp: boolean): FundingAverage | null {
  const [avg, setAvg] = useState<{ symbol: string; value: FundingAverage } | null>(null);
  useEffect(() => {
    if (!symbol || !perp) return;
    let cancelled = false;
    const load = () => {
      api
        .fundingAverage(symbol)
        .then((value) => {
          if (!cancelled) setAvg({ symbol, value });
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, FUNDING_AVERAGE_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, perp]);
  return perp && avg?.symbol === symbol ? avg.value : null;
}

export function Header({
  markets,
  symbol,
  onSymbolChange,
  network,
  connected,
  tradingEnabled,
  editing,
  onEditToggle,
  onResetLayout,
}: HeaderProps) {
  const [killOpen, setKillOpen] = useState(false);
  const [killBusy, setKillBusy] = useState(false);

  useEffect(() => {
    if (symbol) pushRecent(symbol);
  }, [symbol]);
  const quotes = useLiveQuotes();
  const selected = preferPerpMarket(markets, symbol) ?? null;
  const current = selected ? overlayQuote(selected, quotes[selected.market_index]) : null;
  const account = useLiveAccount();
  const bbo = useLiveBbo();
  const health = useFeedHealth();
  const algoBook = useLiveAlgos();
  const autoKill = useAutoKill();
  const { working: workingAlgos } = algoBlotter(algoBook);
  const algosRunning = workingAlgos.filter((a) => algoIsWorking(a.status)).length;
  const plannersRunning = workingAlgos.filter(
    (a) => a.algo_type === "planner" && algoIsWorking(a.status)
  ).length;
  const trailStopsRunning = workingAlgos.filter(
    (a) => a.algo_type === "trail" && a.trail?.kind === "stop" && algoIsWorking(a.status)
  ).length;
  const bid = parseFloat(bbo.bid ?? "");
  const ask = parseFloat(bbo.ask ?? "");
  const spot = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid > 0 ? bid : ask > 0 ? ask : null;
  const mark = current?.mark_price ?? null;
  const distPct =
    mark != null && spot != null && spot !== 0 ? ((mark - spot) / spot) * 100 : null;

  const marketStatus = !connected
    ? health.market_ws === "live" || health.last_msg_at
      ? "reconnecting"
      : "connecting"
    : health.market_ws === "live"
      ? "live"
      : health.market_ws === "stale"
        ? "stale"
        : health.market_ws === "reconnecting"
          ? "reconnecting"
          : "stale";

  const accountStatus =
    health.account_ws === "live"
      ? "live"
      : health.account_ws === "stale"
        ? "stale"
        : health.account_ws === "down"
          ? "down"
          : "reconnecting";

  const worst =
    marketStatus === "live" && accountStatus === "live"
      ? "live"
      : marketStatus === "connecting" && accountStatus !== "down"
        ? "connecting"
        : marketStatus === "stale" || accountStatus === "stale" || marketStatus === "reconnecting" || accountStatus === "reconnecting"
          ? "stale"
          : "down";

  // Lighter refusing everyone (maintenance, restart) is not our feed going stale: say so.
  const venueDown = worst !== "live" && health.venue_down_since > 0;
  const venueDownTitle = venueDown
    ? `Lighter unavailable since ${formatClock(health.venue_down_since)} UTC` +
      (health.venue_down_reason ? ` (${health.venue_down_reason})` : "") +
      " — usually venue maintenance. Reconnecting on its own."
    : undefined;
  const statusLabel = venueDown
    ? "Lighter down"
    : worst === "live" ? "Live" : worst === "connecting" ? "Connecting" : worst === "stale" ? "Stale" : "Down";
  const statusVariant = worst === "live" ? "bid" : worst === "connecting" ? "muted" : "ask";

  const fundingApr = current?.funding_apr ?? null;
  const fundingRate = current?.funding_rate ?? null;
  const fundingAverage = useFundingAverage(
    current?.symbol ?? "",
    current?.is_perp !== false && fundingRate != null
  );
  const oi = current?.open_interest ?? null;

  const openPositions = (account?.positions ?? []).filter((p) => parseFloat(p.size) !== 0);

  const markTitle =
    mark != null && spot != null
      ? `Mark ${formatPrice(mark)} vs book mid ${formatPrice(spot)}`
      : mark != null
        ? `Mark ${formatPrice(mark)}`
        : undefined;
  const fundingTitle = fundingTooltip(fundingRate, fundingApr, fundingAverage);

  const distClass =
    distPct == null
      ? undefined
      : distPct > 0.002
        ? "text-bid"
        : distPct < -0.002
          ? "text-ask"
          : undefined;
  const fundingClass =
    fundingApr == null ? "text-muted-foreground" : fundingApr >= 0 ? "text-ask" : "text-bid";

  const runKill = async (flatten: boolean) => {
    setKillBusy(true);
    try {
      const res = await api.kill(flatten);
      if (res.algos) setAlgo(res.algos);
      if (res.status === "killed") {
        notifyOk(flatten ? "Kill: algos stopped, orders cancelled, flatten sent" : "Kill: algos stopped, orders cancelled");
      } else {
        const failed = [
          res.algo_error ? "algo stop" : null,
          res.cancel_ok === false ? "cancel-all" : null,
          res.flatten?.some((leg) => !leg.ok) ? "flatten" : null,
        ].filter(Boolean);
        notifyWarn(
          "Kill partial",
          failed.length
            ? `Failed: ${failed.join(", ")}. Check positions and open orders`
            : "Check positions and open orders"
        );
      }
      setKillOpen(false);
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Kill failed");
    } finally {
      setKillBusy(false);
    }
  };

  const flattenLegs = openPositions.map((p) => {
    const sz = Math.abs(parseFloat(p.size) || 0);
    const px = parseFloat(p.mark_price) || parseFloat(p.entry_price) || 0;
    return { symbol: p.symbol, size: sz, notional: sz * px };
  });
  const flattenNotional = flattenLegs.reduce((s, l) => s + l.notional, 0);

  let healthBadge: ReactNode = (
    <Badge variant={statusVariant} title={venueDownTitle}>
      <span
        className={cn(
          "inline-block size-1.5 rounded-full",
          worst === "live" ? "bg-bid" : worst === "connecting" ? "bg-muted-foreground" : "bg-ask"
        )}
      />
      {statusLabel}
    </Badge>
  );

  return (
    <div className="shrink-0">
      <header className="grid h-11 grid-cols-[auto_1fr_auto] items-center gap-4 border-b-[0.5px] border-border bg-background px-3">
        <div className="flex min-w-0 items-center justify-self-start">
          <MarketPicker markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />
          <HeaderFavorite symbol={symbol} />
        </div>

        <div className="flex min-w-0 items-center justify-center gap-3 overflow-x-auto">
          <HeaderStat
            label="Mark"
            value={mark != null ? formatPrice(mark) : "—"}
            hint={distPct != null ? formatPct(distPct) : undefined}
            hintClass={distClass}
            title={markTitle}
            loud
          />
          <StatRule />
          <HeaderStat
            label="Funding"
            value={formatApr(fundingApr)}
            valueClass={fundingClass}
            hint={fundingApr != null ? "APR" : undefined}
            aside={<FundingAverageAside avg={fundingAverage} />}
            title={fundingTitle}
          />
          <StatRule />
          <HeaderStat label="OI" value={formatOi(oi)} />
        </div>

        <div className="flex min-w-0 items-center justify-end gap-2 justify-self-end">
          <PortfolioToday enabled={tradingEnabled} />
          {account ? (
            <HeaderStat
              label="Margin"
              value={formatPrice(account.portfolio_margin ?? "0", 2)}
              title="Portfolio margin"
            />
          ) : null}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className="rounded-lg outline-none focus-visible:ring-1 focus-visible:ring-ring">
                {healthBadge}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuGroup>
                <DropdownMenuLabel>Feeds</DropdownMenuLabel>
                {venueDown && (
                  <DropdownMenuItem disabled className="text-ask">
                    Lighter down since {formatClock(health.venue_down_since)} UTC
                    {health.venue_down_reason ? ` · ${health.venue_down_reason}` : ""}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem disabled>
                  Market {health.market_ws}
                  {health.trade_subs_target
                    ? ` · trades ${health.trade_subs}/${health.trade_subs_target}`
                    : ""}
                </DropdownMenuItem>
                <DropdownMenuItem disabled>Account {health.account_ws}</DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>

          {algosRunning > 0 && (
            <Badge variant="warn">
              {algosRunning} algo{algosRunning === 1 ? "" : "s"}
            </Badge>
          )}
          <Badge variant="outline">{network}</Badge>
          {!tradingEnabled && <Badge variant="muted">Read-only</Badge>}
          {tradingEnabled && autoKill.armed && (
            <Badge
              variant="warn"
              className="cursor-pointer"
              onClick={() => setKillOpen(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setKillOpen(true);
                }
              }}
              role="button"
              tabIndex={0}
            >
              Auto kill
              {autoKill.loss_usd != null ? ` -${autoKill.loss_usd}` : ""}
              {autoKill.profit_usd != null ? ` / +${autoKill.profit_usd}` : ""}
            </Badge>
          )}
          {tradingEnabled && (
            <Button type="button" variant="danger" size="sm" className="h-7" onClick={() => setKillOpen(true)}>
              Kill
            </Button>
          )}

          <Button asChild variant="ghost" size="sm" className="h-7">
            <a href={PORTFOLIO_PATH} target="_blank" rel="noopener">
              <Wallet data-icon="inline-start" />
              Portfolio
            </a>
          </Button>
          <Button asChild variant="ghost" size="sm" className="h-7">
            <a href={JOURNAL_PATH} target="_blank" rel="noopener">
              <BookOpen data-icon="inline-start" />
              Journal
            </a>
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant={editing ? "outline" : "ghost"} size="sm" className="h-7">
                <LayoutGrid data-icon="inline-start" />
                {editing ? "Done" : "Layout"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-44">
              <DropdownMenuGroup>
                <DropdownMenuItem onSelect={onEditToggle}>
                  {editing ? "Done editing" : "Edit layout"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={onResetLayout}>Reset layout</DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <Dialog open={killOpen} onOpenChange={setKillOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Kill switch</DialogTitle>
            <DialogDescription>
              Stop all algos and cancel every open order. Optionally flatten every open
              position with market reduce-only orders.
              {plannersRunning > 0 && (
                <span className="mt-2 block text-warn">
                  {plannersRunning === 1 ? "A Planner is" : `${plannersRunning} Planners are`} live.
                  Stop + cancel takes off its stop: without a flatten, the Position is left with
                  no stop.
                </span>
              )}
              {trailStopsRunning > 0 && (
                <span className="mt-2 block text-warn">
                  {trailStopsRunning === 1 ? "A Trail Stop is" : `${trailStopsRunning} Trail Stops are`}{" "}
                  live. Stop + cancel takes it off: without a flatten, its Position is left with no
                  stop.
                </span>
              )}
              {openPositions.length > 0 && (
                <span className="mt-2 block font-mono text-base text-foreground">
                  Flatten: {openPositions.length} position
                  {openPositions.length === 1 ? "" : "s"}
                  {flattenNotional > 0
                    ? ` · ~${formatUsdCompact(flattenNotional) ?? formatPrice(flattenNotional, 0)} notional`
                    : null}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:justify-end">
            <Button type="button" variant="ghost" disabled={killBusy} onClick={() => setKillOpen(false)}>
              Cancel
            </Button>
            <Button type="button" variant="outline" disabled={killBusy} onClick={() => runKill(false)}>
              Stop + cancel
            </Button>
            <Button type="button" variant="destructive" disabled={killBusy} onClick={() => runKill(true)}>
              Stop + flatten
            </Button>
          </DialogFooter>
          <AutoKillSection tradingEnabled={tradingEnabled} />
        </DialogContent>
      </Dialog>
      <FavoritesBar markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />
    </div>
  );
}
