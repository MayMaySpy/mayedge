import { useRef, useState } from "react";
import { notifyErr, notifyOrder } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTradingReady } from "@/hooks/useTradingReady";
import { api, type Market } from "@/lib/api";
import { useLiveAccount, useLiveBbo } from "@/lib/liveData";
import { useQuickSize } from "@/lib/quickSizes";
import { parseQuickSize } from "@/lib/quickTrade";
import { useAxisTicket } from "@/lib/axisTicket";
import { cn } from "@/lib/utils";

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
  const { armed: axisArmed } = useAxisTicket();
  const [pos, setPos] = useState<Pos>(loadPos);
  const [loading, setLoading] = useState(false);
  const [moving, setMoving] = useState(false);
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

  const startMove = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest("button, input, textarea")) return;
    const panel = panelRef.current;
    const parent = panel?.offsetParent as HTMLElement | null;
    if (!panel || !parent) return;
    e.preventDefault();
    e.stopPropagation();
    panel.setPointerCapture(e.pointerId);
    setMoving(true);
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

  const onMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || d.pw <= 0 || d.ph <= 0) return;
    const maxX = Math.max(0, 1 - d.w / d.pw);
    const maxY = Math.max(0, 1 - d.h / d.ph);
    setPos({
      x: Math.min(maxX, Math.max(0, d.x + (e.clientX - d.px) / d.pw)),
      y: Math.min(maxY, Math.max(0, d.y + (e.clientY - d.py) / d.ph)),
    });
  };

  const endMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setMoving(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
    setPos((p) => {
      try {
        localStorage.setItem(POS_KEY, JSON.stringify(p));
      } catch {
        /* ignore */
      }
      return p;
    });
  };

  const fire = async (side: "buy" | "sell") => {
    if (!market || !tradingEnabled || !feed.ready || loading) {
      if (!feed.ready && feed.reason) notifyErr(feed.reason);
      return;
    }
    const sized = parseQuickSize(qty, market, side, account, bbo);
    if (!sized.ok) {
      notifyErr(sized.error);
      return;
    }
    setLoading(true);
    try {
      await api.placeMarketOrder({
        market_index: market.market_index,
        side,
        size: sized.size,
        slippage: slipFrac(),
        reduce_only: false,
      });
      notifyOrder({ kind: "market", side, size: sized.size, symbol: market.symbol });
    } catch (err) {
      notifyErr(err instanceof Error ? err.message : "Order failed");
    } finally {
      setLoading(false);
    }
  };

  const live = parseFloat(qty) > 0;
  const disabled = loading || !tradingEnabled || !market || !live || !feed.ready;

  return (
    <div
      ref={panelRef}
      title="Drag to move"
      className={cn(
        "pointer-events-auto absolute z-20 w-48 rounded-sm border border-rule bg-panel/95 p-1.5 shadow-[0_8px_28px_rgba(0,0,0,0.45)]",
        moving ? "cursor-grabbing" : "cursor-grab"
      )}
      style={{ left: `${pos.x * 100}%`, top: `${pos.y * 100}%` }}
      onPointerDown={(e) => {
        e.stopPropagation();
        startMove(e);
      }}
      onPointerMove={onMove}
      onPointerUp={endMove}
      onPointerCancel={endMove}
    >
      <div className="flex items-center gap-0.5">
        <Button
          type="button"
          variant="buy"
          size="sm"
          className="h-8 flex-1 cursor-pointer px-1"
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
            if (e.key === "Enter") e.preventDefault();
          }}
          className="h-8 w-16 shrink-0 cursor-text px-1 text-center font-mono text-xs tabular-nums"
        />
        <Button
          type="button"
          variant="sell"
          size="sm"
          className="h-8 flex-1 cursor-pointer px-1"
          disabled={disabled}
          onClick={() => void fire("sell")}
        >
          Sell
        </Button>
      </div>
      {axisArmed ? (
        <div className="mt-1 text-center font-mono text-[9px] uppercase tracking-wide text-muted-foreground">
          axis
        </div>
      ) : null}
    </div>
  );
}
