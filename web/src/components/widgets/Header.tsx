import { useState } from "react";
import type { ReactNode } from "react";
import { toast } from "sonner";
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
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { FavoritesBar } from "@/components/widgets/FavoritesBar";
import { MarketPicker } from "@/components/widgets/MarketPicker";
import type { Market } from "@/lib/api";
import { preferPerpMarket, algoBlotter, algoIsWorking } from "@/lib/algos";
import { api } from "@/lib/api";
import { useFeedHealth, useLiveAccount, useLiveAlgos, useLiveBbo, setAlgo } from "@/lib/liveData";
import { cn, formatApr, formatPct, formatPrice, formatUsdCompact } from "@/lib/utils";

interface HeaderProps {
  markets: Market[];
  symbol: string;
  onSymbolChange: (symbol: string) => void;
  network: string;
  connected: boolean;
  tradingEnabled: boolean;
  markPrice?: number | null;
  editing: boolean;
  onEditToggle: () => void;
}

function num(value: string | undefined) {
  const x = parseFloat(value ?? "");
  return Number.isFinite(x) ? x : 0;
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
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint?: string;
  hintClass?: string;
  title?: string;
}) {
  const body = (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="font-sans text-[11px] text-muted">{label}</span>
      <span className={cn("font-mono text-[11px] tabular-nums text-text", valueClass)}>{value}</span>
      {hint ? (
        <span className={cn("font-mono text-[10px] tabular-nums text-muted", hintClass)}>{hint}</span>
      ) : null}
    </span>
  );
  if (!title) return body;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex cursor-default rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bid"
        >
          {body}
        </button>
      </TooltipTrigger>
      <TooltipContent>{title}</TooltipContent>
    </Tooltip>
  );
}

function StatRule() {
  return <Separator orientation="vertical" className="h-3.5 self-center bg-rule" />;
}

function fundingTooltip(rate: number | null, apr: number | null): string | undefined {
  if (rate == null) return undefined;
  const parts = [`${(rate * 100).toFixed(4)}% per hour`];
  if (apr != null && apr > 0) parts.push("longs pay shorts");
  else if (apr != null && apr < 0) parts.push("shorts pay longs");
  if (apr != null) parts.push(`${formatApr(apr)} APR`);
  return parts.join(". ");
}

function oiTooltip(
  oi: number | null,
  cap: number | null,
  util: number | null
): string | undefined {
  if (oi == null) return undefined;
  if (util != null) return `${formatOi(oi)} open interest, ${formatOi(cap)} cap (${util.toFixed(0)}% used)`;
  return `${formatOi(oi)} open interest`;
}

export function Header({
  markets,
  symbol,
  onSymbolChange,
  network,
  connected,
  tradingEnabled,
  markPrice,
  editing,
  onEditToggle,
}: HeaderProps) {
  const [killOpen, setKillOpen] = useState(false);
  const [killBusy, setKillBusy] = useState(false);
  const current = preferPerpMarket(markets, symbol) ?? null;
  const account = useLiveAccount();
  const bbo = useLiveBbo();
  const health = useFeedHealth();
  const algoBook = useLiveAlgos();
  const { working: workingAlgos } = algoBlotter(algoBook);
  const chaseRunning = workingAlgos.filter((a) => algoIsWorking(a.status)).length;
  const bid = parseFloat(bbo.bid ?? "");
  const ask = parseFloat(bbo.ask ?? "");
  const spot = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid > 0 ? bid : ask > 0 ? ask : null;
  const mark = markPrice ?? null;
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
  const accountLabel =
    accountStatus === "live"
      ? "Acct live"
      : accountStatus === "stale"
        ? "Acct stale"
        : accountStatus === "down"
          ? "Acct down"
          : "Acct reconnect";
  const accountVariant =
    accountStatus === "live" ? "bid" : accountStatus === "down" ? "muted" : "ask";
  const accountDot =
    accountStatus === "live"
      ? "bg-bid"
      : accountStatus === "down"
        ? "bg-muted-foreground"
        : "bg-ask";

  const statusLabel =
    marketStatus === "live"
      ? "Live"
      : marketStatus === "stale"
        ? "Stale"
        : marketStatus === "connecting"
          ? "Connecting"
          : "Reconnecting";
  const statusVariant =
    marketStatus === "live" ? "bid" : marketStatus === "connecting" ? "muted" : "ask";
  const statusDot =
    marketStatus === "live"
      ? "bg-bid"
      : marketStatus === "connecting"
        ? "bg-muted-foreground"
        : "bg-ask";

  const fundingApr = current?.funding_apr ?? null;
  const fundingRate = current?.funding_rate ?? null;
  const oi = current?.open_interest ?? null;
  const oiCap = current?.open_interest_limit ?? null;
  const oiUtil = oi != null && oiCap != null && oiCap > 0 ? (oi / oiCap) * 100 : null;

  const openPositions = (account?.positions ?? []).filter((p) => parseFloat(p.size) !== 0);
  const usedMargin = openPositions.reduce((sum, p) => sum + num(p.allocated_margin), 0);

  const markTitle =
    mark != null && spot != null
      ? `Mark ${formatPrice(mark)} vs book mid ${formatPrice(spot)}`
      : mark != null
        ? `Mark ${formatPrice(mark)}`
        : undefined;
  const fundingTitle = fundingTooltip(fundingRate, fundingApr);
  const oiTitle = oiTooltip(oi, oiCap, oiUtil);
  const statusTitle = [
    health.trade_subs_target ? `trade subs ${health.trade_subs}/${health.trade_subs_target}` : null,
    `market ${health.market_ws}`,
    `account ${health.account_ws}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const distClass =
    distPct == null
      ? undefined
      : distPct > 0.002
        ? "text-bid"
        : distPct < -0.002
          ? "text-ask"
          : undefined;
  const fundingClass =
    fundingApr == null ? "text-muted" : fundingApr >= 0 ? "text-ask" : "text-bid";
  const oiUtilClass =
    oiUtil == null
      ? undefined
      : oiUtil >= 90
        ? "text-ask"
        : oiUtil >= 75
          ? "text-warn"
          : undefined;

  const runKill = async (flatten: boolean) => {
    setKillBusy(true);
    try {
      const res = await api.kill(flatten);
      if (res.algos) setAlgo(res.algos);
      if (res.status === "killed") {
        toast.success(
          flatten ? "Kill: algos stopped, orders cancelled, flatten sent" : "Kill: algos stopped, orders cancelled"
        );
      } else {
        toast.warning("Kill partial — check positions and open orders");
      }
      setKillOpen(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Kill failed");
    } finally {
      setKillBusy(false);
    }
  };

  let accountBadge: ReactNode = (
    <Badge variant={accountVariant}>
      <span className={cn("inline-block size-1.5 rounded-full", accountDot)} />
      {accountLabel}
    </Badge>
  );
  if (statusTitle) {
    accountBadge = (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex">{accountBadge}</span>
        </TooltipTrigger>
        <TooltipContent>{statusTitle}</TooltipContent>
      </Tooltip>
    );
  }

  let statusBadge: ReactNode = (
    <Badge variant={statusVariant}>
      <span className={cn("inline-block size-1.5 rounded-full", statusDot)} />
      {statusLabel}
    </Badge>
  );
  if (statusTitle) {
    statusBadge = (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex">{statusBadge}</span>
        </TooltipTrigger>
        <TooltipContent>Market feed: {health.market_ws}</TooltipContent>
      </Tooltip>
    );
  }

  const flattenLegs = openPositions.map((p) => {
    const sz = Math.abs(parseFloat(p.size) || 0);
    const px = parseFloat(p.mark_price) || parseFloat(p.entry_price) || 0;
    return { symbol: p.symbol, size: sz, notional: sz * px };
  });
  const flattenNotional = flattenLegs.reduce((s, l) => s + l.notional, 0);

  return (
    <div className="shrink-0">
      <header className="grid h-9 grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-rule bg-panel px-3">
        <div className="min-w-0 justify-self-start flex items-center gap-2">
          <MarketPicker markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />
        </div>

        <div className="flex min-w-0 items-center gap-3 overflow-x-auto">
          <HeaderStat
            label="Mark"
            value={mark != null ? formatPrice(mark) : "—"}
            hint={distPct != null ? formatPct(distPct) : undefined}
            hintClass={distClass}
            title={markTitle}
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
          <HeaderStat
            label="OI"
            value={formatOi(oi)}
            hint={oiUtil != null ? `${oiUtil.toFixed(0)}%` : undefined}
            hintClass={oiUtilClass}
            title={oiTitle}
          />
        </div>

        <div className="flex min-w-0 items-center justify-end gap-3 justify-self-end">
          {account ? (
            <div className="flex min-w-0 items-center gap-3 overflow-x-auto">
              <HeaderStat
                label="Collateral"
                value={formatPrice(account.collateral, 2)}
                title="Account collateral"
              />
              <HeaderStat
                label="Available"
                value={formatPrice(account.available, 2)}
                title="Free collateral"
              />
              {usedMargin > 0 && (
                <HeaderStat
                  label="In use"
                  value={formatPrice(usedMargin, 2)}
                  valueClass="text-muted"
                  title="Margin allocated to open positions"
                />
              )}
            </div>
          ) : null}

          <div className="flex shrink-0 items-center gap-2 font-mono text-[10px]">
            {statusBadge}
            {accountBadge}
            {chaseRunning > 0 && (
              <Badge variant="warn" title="Working chase algos">
                {chaseRunning} chase
              </Badge>
            )}
            <Badge variant="muted">{network}</Badge>
            {!tradingEnabled && <Badge variant="muted">Read-only</Badge>}
            {tradingEnabled && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-6 border-ask/40 px-2 text-[10px] text-ask hover:bg-ask/10"
                onClick={() => setKillOpen(true)}
              >
                Kill
              </Button>
            )}
          </div>

          <Button
            type="button"
            variant={editing ? "outline" : "ghost"}
            size="sm"
            onClick={onEditToggle}
            className={editing ? "font-semibold text-text" : undefined}
          >
            {editing ? "Done" : "Edit"}
          </Button>
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
                <span className="mt-2 block font-mono text-[11px] text-text">
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
            <Button type="button" variant="danger" disabled={killBusy} onClick={() => runKill(true)}>
              Stop + flatten
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <FavoritesBar markets={markets} symbol={symbol} onSymbolChange={onSymbolChange} />
    </div>
  );
}
