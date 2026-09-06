import { GripHorizontal } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTradingReady } from "@/hooks/useTradingReady";
import { api, type Market } from "@/lib/api";
import { parseDecimal } from "@/lib/numbers";
import { useLiveAccount, useLiveBbo } from "@/lib/liveData";
import { useQuickSize } from "@/lib/quickSizes";
import { maxOrderSize } from "@/components/widgets/orderTicket/math";

const POS_KEY = "mayedge-quick-panel-pos";
const SLIP_KEY = "mayedge-slippage-pct";

interface Pos {
  x: number;
  y: number;
}

function loadPos(): Pos {
  try {
    const raw = localStorage.getItem(POS_KEY);
    const p = raw ? (JSON.parse(raw) as Pos) : null;
    if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) {
      return { x: clamp01(p.x), y: clamp01(p.y) };
    }
  } catch {
    /* ignore */
  }
  return { x: 0.03, y: 0.72 };
}

function clamp01(n: number) {
  return Math.min(1, Math.max(0, n));
}

function slipFrac() {
  try {
    const n = parseFloat(localStorage.getItem(SLIP_KEY) ?? "");
    if (Number.isFinite(n) && n > 0 && n <= 50) return n / 100;
  } catch {
    /* ignore */
  }
  return 0.01;
}

function trimQty(n: number, decimals: number): string {
  if (!Number.isFinite(n) || n <= 0) return "";
  const d = Math.max(0, Math.min(decimals, 6));
  const f = 10 ** d;
  const q = Math.floor(n * f + 1e-9) / f;
  if (q <= 0) return "";
  return q.toFixed(d).replace(/\.?0+$/, "") || "0";
}

interface QuickTradePanelProps {
  market: Market | null;
  tradingEnabled: boolean;
  connected: boolean;
}

export function QuickTradePanel({ market, tradingEnabled, connected }: QuickTradePanelProps) {
  const feed = useTradingReady({ connected });
  const account = useLiveAccount();
  const bbo = useLiveBbo();
  const { qty, setQty } = useQuickSize();
  const [pos, setPos] = useState<Pos>(loadPos);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    px: number;
    py: number;
    x: number;
    y: number;
    pw: number;
    ph: number;
    w: number;
    h: number;
  } | null>(null);

  const onGripDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const panel = panelRef.current;
    const parent = panel?.offsetParent as HTMLElement | null;
    if (!panel || !parent) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = {
      px: e.clientX,
      py: e.clientY,
      x: pos.x,
      y: pos.y,
      pw: parent.clientWidth,
      ph: parent.clientHeight,
      w: panel.offsetWidth,
      h: panel.offsetHeight,
    };
  };

  const onGripMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || d.pw <= 0 || d.ph <= 0) return;
    const maxX = Math.max(0, 1 - d.w / d.pw);
    const maxY = Math.max(0, 1 - d.h / d.ph);
    setPos({
      x: Math.min(maxX, Math.max(0, d.x + (e.clientX - d.px) / d.pw)),
      y: Math.min(maxY, Math.max(0, d.y + (e.clientY - d.py) / d.ph)),
    });
  };

  const onGripUp = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    setPos((p) => {
      try {
        localStorage.setItem(POS_KEY, JSON.stringify(p));
      } catch {
        /* ignore */
      }
      return p;
    });
  };

  const maxForSide = (side: "buy" | "sell") => {
    if (!market) return 0;
    const bid = parseFloat(bbo.bid ?? "");
    const ask = parseFloat(bbo.ask ?? "");
    const spot = bid > 0 && ask > 0 ? (bid + ask) / 2 : ask > 0 ? ask : bid;
    const pos = account?.positions.find((p) => p.market_index === market.market_index);
    const signedPos = pos ? parseFloat(pos.size) : 0;
    const lev = pos?.leverage ?? 1;
    const available = parseFloat(account?.trade_available ?? account?.available ?? "0");
    const px = side === "buy" ? (ask > 0 ? ask : spot) : bid > 0 ? bid : spot;
    return maxOrderSize({
      available,
      leverage: lev,
      price: px,
      signedPos,
      side,
      reduceOnly: false,
    });
  };

  const fire = async (side: "buy" | "sell") => {
    if (!market || !tradingEnabled || !feed.ready || loading) {
      if (!feed.ready && feed.reason) toast.error(feed.reason);
      return;
    }
    const parsed = parseDecimal(qty);
    const decimals = market.size_decimals ?? 4;
    const q = parsed != null ? trimQty(parsed, decimals) : "";
    if (!q) {
      toast.error("Set a size");
      return;
    }
    const max = maxForSide(side);
    if (max > 0 && parsed != null && parsed > max + 1e-9) {
      toast.error(`Max ${trimQty(max, decimals)} ${market.symbol}`);
      return;
    }
    setLoading(true);
    try {
      await api.placeMarketOrder({
        market_index: market.market_index,
        side,
        size: q,
        slippage: slipFrac(),
        reduce_only: false,
      });
      toast.success(`${side === "buy" ? "Buy" : "Sell"} ${q} ${market.symbol}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Order failed");
    } finally {
      setLoading(false);
    }
  };

  const live = parseFloat(qty) > 0;
  const disabled = loading || !tradingEnabled || !market || !live || !feed.ready;

  return (
    <div
      ref={panelRef}
      className="pointer-events-auto absolute z-20 w-52 rounded-sm border border-rule bg-panel/95 shadow-[0_8px_28px_rgba(0,0,0,0.45)]"
      style={{ left: `${pos.x * 100}%`, top: `${pos.y * 100}%` }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div
        className="flex h-5 cursor-grab items-center justify-center text-muted active:cursor-grabbing"
        onPointerDown={onGripDown}
        onPointerMove={onGripMove}
        onPointerUp={onGripUp}
        onPointerCancel={onGripUp}
      >
        <GripHorizontal className="size-3.5" />
      </div>
      <div className="px-1.5 pb-0.5 font-mono text-[10px] text-muted">
        {market?.symbol ?? "—"} · mkt
      </div>
      <div className="flex items-center gap-0.5 px-1.5 pb-1.5">
        <Button
          type="button"
          variant="buy"
          size="sm"
          className="h-8 flex-1 px-1"
          disabled={disabled}
          onClick={() => void fire("buy")}
        >
          Buy
        </Button>
        <Input
          value={qty}
          inputMode="decimal"
          placeholder="size"
          onChange={(e) => setQty(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
            }
          }}
          className="h-8 w-18 shrink-0 px-1 text-center font-mono text-xs tabular-nums"
        />
        <Button
          type="button"
          variant="sell"
          size="sm"
          className="h-8 flex-1 px-1"
          disabled={disabled}
          onClick={() => void fire("sell")}
        >
          Sell
        </Button>
      </div>
    </div>
  );
}
