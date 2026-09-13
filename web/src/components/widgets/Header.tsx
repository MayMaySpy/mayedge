import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { LayoutGrid } from "lucide-react";
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
import { FavoritesBar } from "@/components/widgets/FavoritesBar";
import { MarketPicker } from "@/components/widgets/MarketPicker";
import type { Market } from "@/lib/api";
import { preferPerpMarket, algoBlotter, algoIsWorking } from "@/lib/algos";
import { api } from "@/lib/api";
import { pushRecent } from "@/lib/recents";
import { useFeedHealth, useLiveAccount, useLiveAlgos, useLiveBbo, useLiveQuotes, overlayQuote, setAlgo } from "@/lib/liveData";
import { cn, formatApr, formatPct, formatPrice, formatUsdCompact } from "@/lib/utils";
import { formatFundingPct } from "@/lib/marketPicker";

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
  title,
  loud,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
  hintClass?: string;
  title?: string;
  loud?: boolean;
}) {
  const body = (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span
        className={cn(
          "font-mono tabular-nums text-foreground",
          loud ? "text-base font-medium leading-none" : "text-[13px]",
          valueClass
        )}
      >
        {value}
      </span>
      {hint ? (
        <span className={cn("font-mono text-[11px] tabular-nums text-muted-foreground", hintClass)}>
          {hint}
        </span>
      ) : null}
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

function fundingTooltip(rate: number | null, apr: number | null): string | undefined {
  if (rate == null) return undefined;
  const parts = [`${formatFundingPct(rate)} per hour`, `${formatFundingPct(rate * 8)} / 8h`];
  if (apr != null && apr > 0) parts.push("longs pay shorts");
  else if (apr != null && apr < 0) parts.push("shorts pay longs");
  if (apr != null) parts.push(`${formatApr(apr)} APR`);
  return parts.join(". ");
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
  const { working: workingAlgos } = algoBlotter(algoBook);
  const algosRunning = workingAlgos.filter((a) => algoIsWorking(a.status)).length;
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

  const statusLabel =
    worst === "live" ? "Live" : worst === "connecting" ? "Connecting" : worst === "stale" ? "Stale" : "Down";
  const statusVariant = worst === "live" ? "bid" : worst === "connecting" ? "muted" : "ask";

  const fundingApr = current?.funding_apr ?? null;
  const fundingRate = current?.funding_rate ?? null;
  const oi = current?.open_interest ?? null;

  const openPositions = (account?.positions ?? []).filter((p) => parseFloat(p.size) !== 0);

  const markTitle =
    mark != null && spot != null
      ? `Mark ${formatPrice(mark)} vs book mid ${formatPrice(spot)}`
      : mark != null
        ? `Mark ${formatPrice(mark)}`
        : undefined;
  const fundingTitle = fundingTooltip(fundingRate, fundingApr);

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
        notifyWarn("Kill partial", "Check positions and open orders");
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
    <Badge variant={statusVariant}>
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
      <header className="grid h-11 grid-cols-[auto_1fr_auto] items-center gap-4 border-b border-border bg-card px-3">
        <div className="min-w-0 justify-self-start">
          <MarketPicker markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />
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
            title={fundingTitle}
          />
          <StatRule />
          <HeaderStat label="OI" value={formatOi(oi)} />
        </div>

        <div className="flex min-w-0 items-center justify-end gap-2 justify-self-end">
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
          {tradingEnabled && (
            <Button type="button" variant="danger" size="sm" className="h-7" onClick={() => setKillOpen(true)}>
              Kill
            </Button>
          )}

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
              {openPositions.length > 0 && (
                <span className="mt-2 block font-mono text-[12px] text-foreground">
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
        </DialogContent>
      </Dialog>
      <FavoritesBar markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />
    </div>
  );
}
