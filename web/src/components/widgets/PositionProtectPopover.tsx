import { useState, type ReactNode } from "react";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { trimQty } from "@/components/widgets/orderTicket/math";
import { CellInput } from "@/components/widgets/CellInput";
import { TrailExitSection } from "@/components/widgets/trail/TrailExitSection";
import { isAlgoClientOrder } from "@/lib/algoPlugins";
import {
  isLongPosition,
  type AlgoState,
  type OpenOrder,
  type Position,
  type StopTakeRequest,
} from "@/lib/api";
import { defaultTrailExitDraft, TRAIL_KIND_LABEL, trailBody, trailExitProblem } from "@/lib/trail";
import { canonicalDecimal, decimalInput, parseDecimal, stripFractionalZeros } from "@/lib/numbers";
import {
  pnlAtTrigger,
  pnlFromRoe,
  protectCloseSize,
  protectOrderLabel,
  protectTriggersFromOrders,
  protectTriggersLabel,
  roeFromPnl,
  stopTakeKind,
  triggerFromPnl,
  triggerOnCorrectSide,
  workingProtectOrders,
} from "@/lib/positionsTable";
import { cn, formatPrice, formatSigned, formatSize } from "@/lib/utils";

type SizeMode = "full" | "partial";
type ExitMode = "fixed" | "trail";
type MoneyUnit = "$" | "%";

const TP_SLIDER_MAX = 150;
const SL_SLIDER_MAX = 75;
const SLIDER_TICKS = Array.from({ length: 17 }, (_, i) => i);

function draftNum(n: number, maxDp: number): string {
  if (!Number.isFinite(n)) return "";
  const d = Math.max(0, Math.min(maxDp, 8));
  return stripFractionalZeros(n.toFixed(d));
}

function emptyForm(seed?: { tp?: string; sl?: string }) {
  return {
    sizeMode: "full" as SizeMode,
    qty: "",
    tpTrigger: seed?.tp ?? "",
    tpLimit: "",
    slTrigger: seed?.sl ?? "",
    slLimit: "",
    gainUnit: "$" as MoneyUnit,
    lossUnit: "$" as MoneyUnit,
    tpMode: "fixed" as ExitMode,
    slMode: "fixed" as ExitMode,
    tpTrail: defaultTrailExitDraft(),
    slTrail: defaultTrailExitDraft(),
  };
}

export function PositionProtectPopover({
  position,
  mark,
  sizeDecimals,
  priceDecimals,
  tradingEnabled,
  busy,
  orders,
  onPlace,
  onCancel,
  lockedBy,
  trails = [],
  onStartTrail,
}: {
  /** Live Trails on this Market (trail-rules.md). A Trail Stop is the Position's stop. */
  trails?: AlgoState[];
  onStartTrail?: (body: Record<string, unknown>) => Promise<void>;
  /** ADR 0015: an algo owns this exit, so the editor shows it and changes nothing. */
  lockedBy?: string | null;
  position: Position;
  mark: number;
  sizeDecimals: number;
  priceDecimals: number;
  tradingEnabled: boolean;
  busy: boolean;
  orders: OpenOrder[];
  onPlace: (body: StopTakeRequest) => Promise<void>;
  onCancel: (orderIndex: string) => Promise<void>;
}) {
  const working = workingProtectOrders(orders, position.market_index);
  const shown = protectTriggersFromOrders(working);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(() => emptyForm(shown));
  const [sending, setSending] = useState(false);

  const posAbs = Math.abs(parseFloat(position.size) || 0);
  const closeIsAsk = isLongPosition(position);
  const entry = parseFloat(position.entry_price) || 0;
  const margin = parseFloat(position.allocated_margin ?? "") || 0;
  const notional = posAbs * (entry > 0 ? entry : mark);
  const qtyNum = parseDecimal(form.qty) ?? 0;
  const closeSize = form.sizeMode === "full" ? posAbs : protectCloseSize(posAbs, "partial", qtyNum);
  const signedClose = closeIsAsk ? closeSize : -closeSize;

  const tpTrig = parseDecimal(form.tpTrigger) ?? 0;
  const slTrig = parseDecimal(form.slTrigger) ?? 0;
  const tpPnl = tpTrig > 0 ? pnlAtTrigger(entry, signedClose, tpTrig) : null;
  const slPnl = slTrig > 0 ? pnlAtTrigger(entry, signedClose, slTrig) : null;
  const tpRoe = tpPnl != null ? roeFromPnl(tpPnl, margin, notional) : null;
  const slRoe = slPnl != null ? roeFromPnl(slPnl, margin, notional) : null;

  const closeSide = closeIsAsk ? "sell" : "buy";
  const liq = n(position.liquidation_price);
  const trailStop = trails.find((t) => t.trail?.kind === "stop") ?? null;
  const tpTrailing = form.tpMode === "trail";
  const slTrailing = form.slMode === "trail";
  const tpOk =
    !tpTrailing && tpTrig > 0 && triggerOnCorrectSide("tp", closeIsAsk, tpTrig, mark);
  const slOk =
    !slTrailing && !trailStop && slTrig > 0 && triggerOnCorrectSide("sl", closeIsAsk, slTrig, mark);
  const tpTrailProblem = tpTrailing
    ? trailExitProblem("tp", form.tpTrail, closeSide, mark, liq, priceDecimals)
    : null;
  const slTrailProblem = slTrailing
    ? trailExitProblem("stop", form.slTrail, closeSide, mark, liq, priceDecimals)
    : null;
  const tpTrailOk = tpTrailing && !tpTrailProblem && !!onStartTrail;
  const slTrailOk = slTrailing && !trailStop && !slTrailProblem && !!onStartTrail;
  const sizeOk = form.sizeMode === "full" || qtyNum > 0;
  const canPlace =
    tradingEnabled && !busy && !sending && sizeOk && (tpOk || slOk || tpTrailOk || slTrailOk);
  // TS4: the Stop Tickets a Trail Stop takes over.
  const replacedStops = working
    .filter((o) => stopTakeKind(o.order_type) === "sl" && !isAlgoClientOrder(o.client_order_index))
    .map((o) => protectOrderLabel(o.order_type, o.trigger_price));

  const applyPnl = (kind: "tp" | "sl", pnl: number) => {
    const trigger = triggerFromPnl(entry, signedClose, pnl);
    const key = kind === "tp" ? "tpTrigger" : "slTrigger";
    setForm((f) => ({ ...f, [key]: trigger != null ? draftNum(trigger, priceDecimals) : "" }));
  };

  const place = async () => {
    if (!canPlace) return;
    const size =
      form.sizeMode === "full"
        ? "0"
        : trimQty(protectCloseSize(posAbs, "partial", qtyNum), sizeDecimals) || "0";
    const body: StopTakeRequest = {
      market_index: position.market_index,
      side: closeIsAsk ? "sell" : "buy",
      size,
      slippage: 0.01,
    };
    const tpTrigger = canonicalDecimal(form.tpTrigger);
    const slTrigger = canonicalDecimal(form.slTrigger);
    if (tpOk && tpTrigger) {
      const limit = canonicalDecimal(form.tpLimit);
      body.tp = {
        kind: limit ? "limit" : "market",
        trigger: tpTrigger,
        ...(limit ? { price: limit } : {}),
      };
    }
    if (slOk && slTrigger) {
      const limit = canonicalDecimal(form.slLimit);
      body.sl = {
        kind: limit ? "limit" : "market",
        trigger: slTrigger,
        ...(limit ? { price: limit } : {}),
      };
    }
    setSending(true);
    try {
      if (tpOk || slOk) await onPlace(body);
      const pct =
        form.sizeMode === "full" || posAbs <= 0 ? 100 : Math.min(100, (qtyNum / posAbs) * 100);
      if (slTrailOk && onStartTrail) {
        await onStartTrail(
          trailBody(form.slTrail, {
            kind: "stop",
            market_index: position.market_index,
            start: canonicalDecimal(form.slTrail.start) ?? null,
            slippage: 0.01,
          })
        );
      }
      if (tpTrailOk && onStartTrail) {
        await onStartTrail(
          trailBody(form.tpTrail, {
            kind: "tp",
            market_index: position.market_index,
            size_pct: String(Number(pct.toFixed(4))),
            slippage: 0.01,
          })
        );
      }
      setOpen(false);
    } catch {
      // The caller has already reported it. Stay open so the entry is not lost.
    } finally {
      setSending(false);
    }
  };

  if (lockedBy) {
    return (
      <span
        title={`${lockedBy} owns the exit on this Market`}
        className="inline-flex items-center gap-1 font-mono text-sm tabular-nums text-muted-foreground"
      >
        <span>{protectTriggersLabel(shown.tp, shown.sl)}</span>
        <span className="text-xs uppercase tracking-wide">{lockedBy}</span>
      </span>
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setForm(emptyForm(protectTriggersFromOrders(working)));
      }}
    >
      <DialogTrigger asChild>
        <button
          type="button"
          title="TP/SL for Position"
          className="inline-flex items-center gap-1 font-mono text-sm tabular-nums text-muted-foreground hover:text-foreground"
        >
          <span>{protectTriggersLabel(shown.tp, shown.sl)}</span>
          <Pencil className="size-3 opacity-50" />
        </button>
      </DialogTrigger>
      <DialogContent
        className="flex max-h-[95vh] w-95 max-w-[calc(100vw-16px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-95"
        onClick={(e) => e.stopPropagation()}
      >
        <DialogHeader className="flex-row items-center justify-between border-b border-rule px-3 py-2.5 pr-10">
          <DialogTitle>TP/SL for Position</DialogTitle>
          <DialogDescription className="sr-only">
            Set take-profit and stop-loss for {position.symbol}
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col">
          <ToggleGroup
            type="single"
            variant="seg"
            size="sm"
            spacing={0}
            value={form.sizeMode}
            onValueChange={(v) => {
              if (v === "full" || v === "partial") setForm((f) => ({ ...f, sizeMode: v }));
            }}
            className="w-full shrink-0 justify-start rounded-none border-b border-rule px-1"
          >
            <ToggleGroupItem
              value="full"
              className="relative h-8 flex-1 rounded-none font-sans text-base data-[state=on]:after:absolute data-[state=on]:after:inset-x-2 data-[state=on]:after:bottom-px data-[state=on]:after:h-0.5 data-[state=on]:after:rounded-full data-[state=on]:after:bg-foreground"
            >
              Entire Position
            </ToggleGroupItem>
            <ToggleGroupItem
              value="partial"
              className="relative h-8 flex-1 rounded-none font-sans text-base data-[state=on]:after:absolute data-[state=on]:after:inset-x-2 data-[state=on]:after:bottom-px data-[state=on]:after:h-0.5 data-[state=on]:after:rounded-full data-[state=on]:after:bg-foreground"
            >
              Partial Position
            </ToggleGroupItem>
          </ToggleGroup>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="flex flex-col gap-1.5 p-3">
            <SummaryRow label="Market" value={position.symbol} />
            {form.sizeMode === "partial" ? (
              <label className="flex items-center justify-between gap-2 text-base">
                <span className="text-muted-foreground">Size</span>
                <input
                  className="h-6 w-28 bg-transparent text-right font-mono text-base tabular-nums outline-none"
                  inputMode="decimal"
                  placeholder="0.00"
                  value={form.qty}
                  onChange={(e) => setForm((f) => ({ ...f, qty: decimalInput(e.target.value) }))}
                />
              </label>
            ) : (
              <SummaryRow
                label="Size"
                value={formatSize(posAbs)}
                className={closeIsAsk ? "text-bid" : "text-ask"}
              />
            )}
            <SummaryRow label="Entry Price" value={formatPrice(position.entry_price, priceDecimals)} />
            <SummaryRow label="Mark Price" value={formatPrice(mark, priceDecimals)} />
            <SummaryRow
              label="Liq. Price"
              value={
                n(position.liquidation_price) > 0
                  ? formatPrice(position.liquidation_price, priceDecimals)
                  : "—"
              }
            />
            <SummaryRow label="TP/SL Slippage" value="Max: 1%" />
          </div>

          {tpTrailing ? (
            <ExitHead title="Take Profit" mode={form.tpMode} onMode={(tpMode) => setForm((f) => ({ ...f, tpMode }))}>
              <TrailExitSection
                kind="tp"
                draft={form.tpTrail}
                closeSide={closeSide}
                mark={mark}
                priceDecimals={priceDecimals}
                problem={tpTrailProblem}
                replaces={[]}
                partial={form.sizeMode === "partial"}
                onChange={(tpTrail) => setForm((f) => ({ ...f, tpTrail }))}
              />
            </ExitHead>
          ) : (
          <ProtectSection
            mode={form.tpMode}
            onMode={(tpMode) => setForm((f) => ({ ...f, tpMode }))}
            title="Take Profit"
            triggerLabel="TP Trigger Price"
            moneyLabel="Gain"
            trigger={form.tpTrigger}
            limit={form.tpLimit}
            unit={form.gainUnit}
            money={moneyDraft(form.gainUnit, tpPnl, tpRoe)}
            pnl={tpPnl}
            sliderMax={TP_SLIDER_MAX}
            sliderValue={sliderValue(tpRoe, TP_SLIDER_MAX)}
            sliderClass="accent-[var(--color-bid)]"
            hint={
              tpTrig > 0 && !tpOk
                ? closeIsAsk
                  ? "Trigger must be above mark"
                  : "Trigger must be below mark"
                : null
            }
            onTrigger={(tpTrigger) => setForm((f) => ({ ...f, tpTrigger }))}
            onLimit={(tpLimit) => setForm((f) => ({ ...f, tpLimit }))}
            onUnit={(gainUnit) => setForm((f) => ({ ...f, gainUnit }))}
            onMoney={(raw) => {
              const n = parseDecimal(raw);
              if (n == null || n <= 0) {
                setForm((f) => ({ ...f, tpTrigger: raw.trim() ? f.tpTrigger : "" }));
                return;
              }
              const pnl = form.gainUnit === "$" ? n : pnlFromRoe(n, margin, notional);
              if (pnl != null) applyPnl("tp", pnl);
            }}
            onSlider={(pct) => {
              if (pct <= 0) {
                setForm((f) => ({ ...f, tpTrigger: "" }));
                return;
              }
              const pnl = pnlFromRoe(pct, margin, notional);
              if (pnl != null) applyPnl("tp", pnl);
            }}
          />
          )}

          {trailStop ? (
            <ExitHead title="Stop Loss">
              <p className="border-t border-rule px-3 py-2.5 text-sm text-muted-foreground">
                {TRAIL_KIND_LABEL.stop} {trailStop.algo_id} is this Position&apos;s stop
                {trailStop.trail?.trigger ? ` at ${formatPrice(trailStop.trail.trigger, priceDecimals)}` : ""}.
                Stop it from Algos to set another.
              </p>
            </ExitHead>
          ) : slTrailing ? (
            <ExitHead title="Stop Loss" mode={form.slMode} onMode={(slMode) => setForm((f) => ({ ...f, slMode }))}>
              <TrailExitSection
                kind="stop"
                draft={form.slTrail}
                closeSide={closeSide}
                mark={mark}
                priceDecimals={priceDecimals}
                problem={slTrailProblem}
                replaces={replacedStops}
                partial={false}
                onChange={(slTrail) => setForm((f) => ({ ...f, slTrail }))}
              />
            </ExitHead>
          ) : (
          <ProtectSection
            mode={form.slMode}
            onMode={(slMode) => setForm((f) => ({ ...f, slMode }))}
            title="Stop Loss"
            triggerLabel="SL Trigger Price"
            moneyLabel="Loss"
            trigger={form.slTrigger}
            limit={form.slLimit}
            unit={form.lossUnit}
            money={moneyDraft(form.lossUnit, slPnl != null ? -slPnl : null, slRoe != null ? -slRoe : null)}
            pnl={slPnl}
            sliderMax={SL_SLIDER_MAX}
            sliderValue={sliderValue(slRoe != null ? -slRoe : null, SL_SLIDER_MAX)}
            sliderClass="accent-[var(--color-ask)]"
            hint={
              slTrig > 0 && !slOk
                ? closeIsAsk
                  ? "Trigger must be below mark"
                  : "Trigger must be above mark"
                : null
            }
            onTrigger={(slTrigger) => setForm((f) => ({ ...f, slTrigger }))}
            onLimit={(slLimit) => setForm((f) => ({ ...f, slLimit }))}
            onUnit={(lossUnit) => setForm((f) => ({ ...f, lossUnit }))}
            onMoney={(raw) => {
              const n = parseDecimal(raw);
              if (n == null || n <= 0) {
                setForm((f) => ({ ...f, slTrigger: raw.trim() ? f.slTrigger : "" }));
                return;
              }
              const mag = form.lossUnit === "$" ? n : pnlFromRoe(n, margin, notional);
              if (mag != null) applyPnl("sl", -Math.abs(mag));
            }}
            onSlider={(pct) => {
              if (pct <= 0) {
                setForm((f) => ({ ...f, slTrigger: "" }));
                return;
              }
              const mag = pnlFromRoe(pct, margin, notional);
              if (mag != null) applyPnl("sl", -Math.abs(mag));
            }}
          />
          )}

          {working.length > 0 ? (
            <div className="flex flex-col gap-1 border-t border-rule px-3 py-2">
              {working.map((o) => (
                <div key={o.order_index} className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      "font-mono text-sm tabular-nums",
                      stopTakeKind(o.order_type) === "sl" ? "text-ask" : "text-bid"
                    )}
                  >
                    {protectOrderLabel(o.order_type, o.trigger_price)}
                  </span>
                  {isAlgoClientOrder(o.client_order_index) ? (
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">Algo</span>
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-1.5 text-xs"
                      disabled={!tradingEnabled || sending}
                      onClick={() => void onCancel(o.order_index)}
                    >
                      Cancel
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ) : null}
          </div>

          <div className="shrink-0 border-t border-rule p-3">
            <Button type="button" className="w-full" disabled={!canPlace} onClick={() => void place()}>
              Submit
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function n(value: string | undefined) {
  const x = parseFloat(value ?? "");
  return Number.isFinite(x) ? x : 0;
}

function moneyDraft(unit: MoneyUnit, pnl: number | null, roe: number | null): string {
  if (unit === "$") return pnl != null ? draftNum(Math.abs(pnl), 2) : "";
  return roe != null ? draftNum(Math.abs(roe), 2) : "";
}

function sliderValue(roe: number | null, max: number): number {
  if (roe == null || !(roe > 0)) return 0;
  return Math.max(0, Math.min(max, roe));
}

function SummaryRow({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex w-full justify-between text-base">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-mono tabular-nums", className)}>{value}</span>
    </div>
  );
}

function ModeToggle({ mode, onMode }: { mode: ExitMode; onMode: (mode: ExitMode) => void }) {
  return (
    <ToggleGroup
      type="single"
      variant="seg"
      size="sm"
      spacing={0}
      value={mode}
      onValueChange={(v) => {
        if (v === "fixed" || v === "trail") onMode(v);
      }}
      aria-label="Fixed or Trail"
    >
      <ToggleGroupItem value="fixed" className="h-6 px-2">
        Fixed
      </ToggleGroupItem>
      <ToggleGroupItem value="trail" className="h-6 px-2">
        Trail
      </ToggleGroupItem>
    </ToggleGroup>
  );
}

function ExitHead({
  title,
  mode,
  onMode,
  children,
}: {
  title: string;
  mode?: ExitMode;
  onMode?: (mode: ExitMode) => void;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-rule">
      <div className="flex items-center justify-between px-3 pt-2 pb-1.5">
        <p className="text-base">{title}</p>
        {mode && onMode ? <ModeToggle mode={mode} onMode={onMode} /> : null}
      </div>
      {children}
    </div>
  );
}

function ProtectSection({
  mode,
  onMode,
  title,
  triggerLabel,
  moneyLabel,
  trigger,
  limit,
  unit,
  money,
  pnl,
  sliderMax,
  sliderValue,
  sliderClass,
  hint,
  onTrigger,
  onLimit,
  onUnit,
  onMoney,
  onSlider,
}: {
  mode: ExitMode;
  onMode: (mode: ExitMode) => void;
  title: string;
  triggerLabel: string;
  moneyLabel: string;
  trigger: string;
  limit: string;
  unit: MoneyUnit;
  money: string;
  pnl: number | null;
  sliderMax: number;
  sliderValue: number;
  sliderClass: string;
  hint: string | null;
  onTrigger: (raw: string) => void;
  onLimit: (raw: string) => void;
  onUnit: (unit: MoneyUnit) => void;
  onMoney: (raw: string) => void;
  onSlider: (pct: number) => void;
}) {
  return (
    <div className="border-t border-rule">
      <div className="flex items-center justify-between px-3 pt-2 pb-1.5">
        <p className="text-base">{title}</p>
        <ModeToggle mode={mode} onMode={onMode} />
      </div>
      <div className="grid grid-cols-2 border-t border-rule">
        <CellInput label={triggerLabel} value={trigger} placeholder="0.0000" onChange={onTrigger} />
        <CellInput
          label={moneyLabel}
          value={money}
          placeholder="0.00"
          onChange={onMoney}
          derived
          className="border-l border-rule"
          trailing={
            <button
              type="button"
              aria-label={unit === "$" ? "Switch to %" : "Switch to $"}
              className="shrink-0 text-sm text-muted-foreground hover:text-foreground"
              onClick={() => onUnit(unit === "$" ? "%" : "$")}
            >
              {unit}
            </button>
          }
        />
      </div>
      <CellInput
        label="Limit Price"
        value={limit}
        placeholder="Market"
        onChange={onLimit}
        className="border-y border-rule"
      />
      <div className="px-3 pt-2 pb-1">
        <input
          type="range"
          min={0}
          max={sliderMax}
          step={1}
          value={Math.round(sliderValue)}
          onChange={(e) => onSlider(Number(e.target.value))}
          className={cn("w-full", sliderClass)}
        />
        <div className="pointer-events-none -mt-2 flex justify-between px-0.5">
          {SLIDER_TICKS.map((i) => (
            <span
              key={i}
              className={cn(
                "rounded-full bg-foreground",
                i % 4 === 0 ? "size-1.5 opacity-20" : "size-0.5 opacity-10"
              )}
            />
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between px-3 pb-2.5 text-base">
        <span className="text-muted-foreground">Estimated PnL</span>
        <span
          className={cn(
            "font-mono tabular-nums",
            pnl == null ? "text-muted-foreground" : pnl >= 0 ? "text-bid" : "text-ask"
          )}
        >
          {pnl == null ? "N/A" : formatSigned(pnl)}
        </span>
      </div>
      {hint ? <p className="px-3 pb-2 text-sm text-ask">{hint}</p> : null}
    </div>
  );
}
