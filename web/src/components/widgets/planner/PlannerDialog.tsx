import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { loadSlipPct } from "@/components/widgets/orderTicket/math";
import { TicketField } from "@/components/widgets/orderTicket/ui";
import {
  api,
  type AlgoState,
  type Market,
  type PlannerPreview,
  type PlannerTargetPlan,
} from "@/lib/api";
import { setAlgo } from "@/lib/liveData";
import { notifyErr, notifyOrder } from "@/lib/notify";
import { decimalInput } from "@/lib/numbers";
import {
  MAX_TARGETS,
  defaultPlannerForm,
  formFromPlanner,
  plannerBody,
  plannerFormBlock,
  replacedLine,
  rLabel,
  plannerTrails,
  runnerPct,
  signedPct,
  stepGapPct,
  stepTargetLabel,
  type PlannerForm,
  type PlannerMode,
  type PlannerSide,
} from "@/lib/plannerPlan";
import { cn, formatPrice, formatSize } from "@/lib/utils";

const PREVIEW_DEBOUNCE_MS = 250;

function trailedBy(t: PlannerTargetPlan): string {
  const d = t.trail_distance ?? "";
  return t.trail_kind === "pct" ? `${d}%` : formatPrice(d);
}

function entryTrailLine(form: PlannerForm, symbol: string): string {
  const et = form.entryTrail;
  const dist = et.distanceKind === "pct" ? `${et.distance}%` : et.distance;
  const ref = form.reference === "last" ? "Last" : "Mark";
  const long = form.side === "buy";
  const wait = et.activation
    ? `Waits for ${symbol} at or ${long ? "below" : "above"} ${et.activation}. Then `
    : "";
  return `${wait}${long ? "buys" : "sells"} when ${ref} ${long ? "rises" : "falls"} ${dist} off its ${long ? "low" : "high"}. Size is worked out from the price it fires at.`;
}

function trailStopLine(form: PlannerForm): string {
  const ts = form.trailStop;
  const dist = ts.unit === "r" ? `${ts.distance}R` : `${ts.distance}%`;
  const from =
    ts.start === "target"
      ? `After TP${ts.after || "?"} fills`
      : ts.start === "last"
        ? form.targets.length
          ? "After the last target fills"
          : "From the fill"
        : `From ${ts.atR || "?"}R`;
  const floor = form.stopSteps === "off" ? "never below where it is" : "never below its stop step";
  return `${from}, the stop follows ${dist} behind the best price, ${floor}.`;
}

function Row({ label, children, tone }: { label: string; children: React.ReactNode; tone?: "bid" | "ask" }) {
  return (
    <div className="flex items-baseline justify-between gap-3 font-mono text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tabular-nums text-text", tone === "bid" && "text-bid", tone === "ask" && "text-ask")}>
        {children}
      </span>
    </div>
  );
}

function Seg<T extends string>({
  value,
  onChange,
  items,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: string }[];
  label: string;
}) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      spacing={0}
      value={value}
      onValueChange={(v) => {
        if (v) onChange(v as T);
      }}
      aria-label={label}
    >
      {items.map((i) => (
        <ToggleGroupItem key={i.value} value={i.value} className="h-7 px-2.5">
          {i.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/**
 * Planner: one trade run from its stop. Enter sends the entry; Attach takes over
 * the open Position; a running Planner re-plans here (docs/planner-rules.md).
 */
interface PlannerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  market: Market;
  mode: PlannerMode;
  /** Attach: the Position's side. Enter: the side to start on. */
  side?: PlannerSide;
  /** A live Planner on this Market: the dialog re-plans it. */
  running?: AlgoState;
}

export function PlannerDialog(props: PlannerDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {/* Mounted per open, so each open starts from a fresh form. */}
      {props.open ? <PlannerDialogBody {...props} /> : null}
    </Dialog>
  );
}

function PlannerDialogBody({ onOpenChange, market, mode, side, running }: PlannerDialogProps) {
  const replan = running != null;
  const [form, setForm] = useState<PlannerForm>(() =>
    running ? formFromPlanner(running) : defaultPlannerForm(side ?? "buy")
  );
  const [drawn, setDrawn] = useState<{ key: string; preview: PlannerPreview | null } | null>(null);
  const [sending, setSending] = useState(false);

  const set = (patch: Partial<PlannerForm>) => setForm((f) => ({ ...f, ...patch }));
  const setTarget = (i: number, patch: Partial<PlannerForm["targets"][number]>) =>
    setForm((f) => ({ ...f, targets: f.targets.map((t, j) => (j === i ? { ...t, ...patch } : t)) }));

  const slippage = Math.min(0.05, Math.max(0, (parseFloat(loadSlipPct()) || 1) / 100));
  const blocked = plannerFormBlock(form, replan ? "attach" : mode);
  const body = plannerBody(form, {
    mode: replan ? "attach" : mode,
    marketIndex: market.market_index,
    slippage,
  });
  const bodyKey = JSON.stringify(body);

  const wantPreview = !replan && !blocked;
  useEffect(() => {
    if (!wantPreview) return;
    let live = true;
    const t = setTimeout(() => {
      api
        .plannerPreview(JSON.parse(bodyKey) as Record<string, unknown>)
        .then((p) => {
          if (live) setDrawn({ key: bodyKey, preview: p });
        })
        .catch(() => {
          if (live) setDrawn({ key: bodyKey, preview: null });
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [wantPreview, bodyKey]);

  // A preview drawn for other inputs is not this plan.
  const preview = wantPreview && drawn?.key === bodyKey ? drawn.preview : null;
  const plan = preview?.plan ?? null;
  const refused = preview?.refused ?? null;
  const replaces = mode === "attach" && !replan ? replacedLine(preview?.replaces ?? []) : null;
  const canSend = !blocked && !sending && (replan || (plan != null && refused == null));
  const long = form.side === "buy";
  const runner = runnerPct(form.targets);

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      const book = replan
        ? await api.plannerReplan({ ...body, algo_id: running?.algo_id })
        : await api.algoStart("planner", body);
      setAlgo(book);
      notifyOrder({
        kind: "planner",
        side: form.side,
        size: plan?.size,
        symbol: market.symbol,
        status: "active",
        note: replan ? "re-planned" : mode === "attach" ? "attached" : undefined,
      });
      onOpenChange(false);
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Planner refused");
    } finally {
      setSending(false);
    }
  };

  const title = replan
    ? `Re-plan ${market.symbol}`
    : mode === "attach"
      ? `Plan ${market.symbol} ${long ? "long" : "short"}`
      : `Planner · ${market.symbol}`;

  return (
    <DialogContent className="max-h-[90vh] overflow-x-hidden overflow-y-auto sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>
          {replan
            ? "Move the stop or redraw the targets. Checked as if new."
            : mode === "attach"
              ? "Takes over this Position's exit: one stop, your targets, and stop steps as they fill."
              : "Entry, stop, targets and size from one stop. The stop steps up as targets fill."}
        </DialogDescription>
      </DialogHeader>

      <FieldGroup className="gap-3">
        {mode === "enter" && !replan && (
          <div className="flex flex-wrap items-center gap-2">
            <Seg
              label="Side"
              value={form.side}
              onChange={(v) => set({ side: v })}
              items={[
                { value: "buy", label: "Long" },
                { value: "sell", label: "Short" },
              ]}
            />
            <Seg
              label="Entry type"
              value={form.entryType}
              onChange={(v) => set({ entryType: v })}
              items={[
                { value: "limit", label: "Limit" },
                { value: "market", label: "Market" },
                { value: "trail", label: "Trail" },
              ]}
            />
          </div>
        )}

        {mode === "enter" && !replan && form.entryType === "trail" && (
          <div className="flex flex-col gap-1">
            <FieldGroup className="grid grid-cols-2 items-start gap-3">
              <TicketField
                id="planner-entry-activation"
                label="Entry Activate at"
                shortLabel="Activate"
                value={form.entryTrail.activation}
                inputMode="decimal"
                placeholder="Now"
                sanitize={decimalInput}
                onChange={(v) => set({ entryTrail: { ...form.entryTrail, activation: v } })}
              />
              <TicketField
                id="planner-entry-distance"
                label="Entry trail distance"
                shortLabel="Distance"
                value={form.entryTrail.distance}
                inputMode="decimal"
                placeholder="1"
                sanitize={decimalInput}
                onChange={(v) => set({ entryTrail: { ...form.entryTrail, distance: v } })}
                addon={
                  <Seg
                    label="Entry distance unit"
                    value={form.entryTrail.distanceKind}
                    onChange={(v) => set({ entryTrail: { ...form.entryTrail, distanceKind: v } })}
                    items={[
                      { value: "pct", label: "%" },
                      { value: "price", label: "Price" },
                    ]}
                  />
                }
              />
            </FieldGroup>
            <span className="font-mono text-xs text-muted-foreground">
              {entryTrailLine(form, market.symbol)}
            </span>
          </div>
        )}

        <FieldGroup className="grid grid-cols-2 items-start gap-3">
          {mode === "enter" && !replan && form.entryType === "limit" ? (
            <TicketField
              id="planner-entry"
              label="Entry price"
              value={form.entryPrice}
              inputMode="decimal"
              placeholder="Entry"
              sanitize={decimalInput}
              onChange={(v) => set({ entryPrice: v })}
            />
          ) : null}
          <TicketField
            id="planner-stop"
            label="Stop"
            value={form.stop}
            inputMode="decimal"
            placeholder="Stop"
            sanitize={decimalInput}
            onChange={(v) => set({ stop: v })}
          />
        </FieldGroup>

        {mode === "enter" && !replan && (
          <div className="flex items-start gap-2">
            <Seg
              label="Size from"
              value={form.sizeMode}
              onChange={(v) => set({ sizeMode: v })}
              items={[
                { value: "risk", label: "Risk %" },
                { value: "size", label: "Size" },
              ]}
            />
            {form.sizeMode === "risk" ? (
              <TicketField
                id="planner-risk"
                label="Risk % of equity"
                value={form.riskPct}
                inputMode="decimal"
                placeholder="1"
                sanitize={decimalInput}
                onChange={(v) => set({ riskPct: v })}
                className="flex-1"
              />
            ) : (
              <TicketField
                id="planner-size"
                label={`Size ${market.symbol}`}
                value={form.size}
                inputMode="decimal"
                placeholder={`Size ${market.symbol}`}
                sanitize={decimalInput}
                onChange={(v) => set({ size: v })}
                className="flex-1"
              />
            )}
          </div>
        )}

        <div className="flex flex-col gap-2">
          {form.targets.map((t, i) => (
            <div key={i} className="flex flex-wrap items-start gap-2">
              <span className="w-9 pt-1.5 font-mono text-xs text-muted-foreground">TP{i + 1}</span>
              <Seg
                label={`Target ${i + 1} kind`}
                value={t.kind}
                onChange={(v) => setTarget(i, { kind: v, value: "" })}
                items={[
                  { value: "r", label: "R" },
                  { value: "price", label: "Price" },
                ]}
              />
              <TicketField
                id={`planner-tp${i}-value`}
                label={t.kind === "r" ? `Target ${i + 1} R` : `Target ${i + 1} price`}
                shortLabel={t.kind === "r" ? "R" : "Price"}
                value={t.value}
                inputMode="decimal"
                placeholder={t.kind === "r" ? "R" : "Price"}
                sanitize={decimalInput}
                onChange={(v) => setTarget(i, { value: v })}
                className="min-w-24 flex-1"
              />
              {/* On a narrow screen these wrap to their own line together. */}
              <div className="ml-auto flex items-start gap-2">
                <Seg
                  label={`Target ${i + 1} order type`}
                  value={t.order}
                  onChange={(v) =>
                    setTarget(
                      i,
                      v === "trail"
                        ? { order: v, trailDistance: t.trailDistance || "0.5", trailUnit: t.trailUnit ?? "r" }
                        : { order: v }
                    )
                  }
                  items={[
                    { value: "limit", label: "Limit" },
                    { value: "trigger", label: "Trigger" },
                    { value: "trail", label: "Trail" },
                  ]}
                />
                <TicketField
                  id={`planner-tp${i}-pct`}
                  label={`Target ${i + 1} % of the Position`}
                  shortLabel="Close"
                  value={t.pct}
                  inputMode="decimal"
                  placeholder="50"
                  sanitize={decimalInput}
                  onChange={(v) => setTarget(i, { pct: v })}
                  addon="%"
                  className="w-36 shrink-0"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label={`Remove target ${i + 1}`}
                  onClick={() => set({ targets: form.targets.filter((_, j) => j !== i) })}
                >
                  <X />
                </Button>
              </div>
              {t.order === "trail" && (
                <div className="flex w-full items-start gap-2 pl-11">
                  <TicketField
                    id={`planner-tp${i}-trail`}
                    label={`Target ${i + 1} trail distance`}
                    shortLabel="Then trails"
                    value={t.trailDistance ?? ""}
                    inputMode="decimal"
                    placeholder="0.5"
                    sanitize={decimalInput}
                    onChange={(v) => setTarget(i, { trailDistance: v })}
                    className="min-w-24 flex-1"
                  />
                  <Seg
                    label={`Target ${i + 1} trail unit`}
                    value={t.trailUnit ?? "r"}
                    onChange={(v) => setTarget(i, { trailUnit: v })}
                    items={[
                      { value: "r", label: "R" },
                      { value: "pct", label: "%" },
                    ]}
                  />
                </div>
              )}
            </div>
          ))}
          <div className="flex items-center justify-between">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7"
              disabled={form.targets.length >= MAX_TARGETS}
              onClick={() =>
                set({ targets: [...form.targets, { kind: "r", value: "", pct: String(runner || ""), order: "limit" }] })
              }
            >
              <Plus data-icon="inline-start" />
              Target
            </Button>
            <span className="font-mono text-xs text-muted-foreground">
              Runner {Number(runner.toFixed(2))}% rides on the stop
              {form.trailStop.start !== "off" ? ", which trails" : ""}
            </span>
          </div>
        </div>

        <Field orientation="horizontal" className="w-full items-center justify-between gap-2">
          <FieldLabel className="text-base font-normal text-muted-foreground">Stop steps</FieldLabel>
          <Seg
            label="Stop steps"
            value={form.stopSteps}
            onChange={(v) => set({ stopSteps: v })}
            items={[
              { value: "off", label: "Off" },
              { value: "breakeven", label: "Breakeven" },
              { value: "ladder", label: "Step up" },
            ]}
          />
        </Field>
        <span className="-mt-2 font-mono text-xs text-muted-foreground">
          {form.stopSteps === "off"
            ? "The stop stays where you put it."
            : form.stopSteps === "breakeven"
              ? "After TP1 the stop moves to breakeven."
              : "After TP1 to breakeven, then after each target to the one before it."}
        </span>

        <div className="flex flex-col gap-2">
          <Field orientation="horizontal" className="w-full flex-wrap items-center justify-between gap-2">
            <FieldLabel className="text-base font-normal text-muted-foreground">Trail stop</FieldLabel>
            <Seg
              label="Trail stop"
              value={form.trailStop.start}
              onChange={(v) => set({ trailStop: { ...form.trailStop, start: v } })}
              items={[
                { value: "off", label: "Off" },
                { value: "target", label: "After TP" },
                { value: "last", label: "After last" },
                { value: "r", label: "At R" },
              ]}
            />
          </Field>
          {form.trailStop.start !== "off" && (
            <div className="flex flex-wrap items-start gap-2">
              {form.trailStop.start === "target" && (
                <TicketField
                  id="planner-trail-after"
                  label="Trail after target number"
                  shortLabel="After TP"
                  value={form.trailStop.after}
                  inputMode="numeric"
                  placeholder="1"
                  sanitize={(raw) => raw.replace(/[^\d]/g, "")}
                  onChange={(v) => set({ trailStop: { ...form.trailStop, after: v } })}
                  className="w-32"
                />
              )}
              {form.trailStop.start === "r" && (
                <TicketField
                  id="planner-trail-at-r"
                  label="Trail from R multiple"
                  shortLabel="At"
                  value={form.trailStop.atR}
                  inputMode="decimal"
                  placeholder="2"
                  addon="R"
                  sanitize={decimalInput}
                  onChange={(v) => set({ trailStop: { ...form.trailStop, atR: v } })}
                  className="w-32"
                />
              )}
              <TicketField
                id="planner-trail-distance"
                label="Trail stop distance"
                shortLabel="Distance"
                value={form.trailStop.distance}
                inputMode="decimal"
                placeholder="1"
                sanitize={decimalInput}
                onChange={(v) => set({ trailStop: { ...form.trailStop, distance: v } })}
                className="min-w-28 flex-1"
              />
              <Seg
                label="Trail stop unit"
                value={form.trailStop.unit}
                onChange={(v) => set({ trailStop: { ...form.trailStop, unit: v } })}
                items={[
                  { value: "r", label: "R" },
                  { value: "pct", label: "%" },
                ]}
              />
            </div>
          )}
          {form.trailStop.start !== "off" && (
            <span className="font-mono text-xs text-muted-foreground">{trailStopLine(form)}</span>
          )}
        </div>

        {plannerTrails(form) && (
          <Field orientation="horizontal" className="w-full items-center justify-between gap-2">
            <FieldLabel className="text-base font-normal text-muted-foreground">Trails follow</FieldLabel>
            <Seg
              label="Trails follow"
              value={form.reference}
              onChange={(v) => set({ reference: v })}
              items={[
                { value: "mark", label: "Mark" },
                { value: "last", label: "Last" },
              ]}
            />
          </Field>
        )}
        {plannerTrails(form) && (
          <span className="-mt-2 font-mono text-xs text-muted-foreground">
            Trail parts follow only while the desk is running.
            {form.reference === "last" ? " On Last the desk closes on a print; a venue backstop sits one step behind." : ""}
          </span>
        )}

        {mode === "enter" && !replan && form.entryType !== "market" && (
          <TicketField
            id="planner-expiry"
            label="Cancel the entry after minutes"
            shortLabel="Expiry"
            value={form.expiryMin}
            inputMode="numeric"
            placeholder="minutes, optional"
            sanitize={(raw) => raw.replace(/[^\d]/g, "")}
            onChange={(v) => set({ expiryMin: v })}
          />
        )}
      </FieldGroup>

      <div className="flex flex-col gap-1 rounded-sm border border-rule p-2" aria-live="polite">
        {blocked ? (
          <span className="font-mono text-sm text-muted-foreground">{blocked}</span>
        ) : replan ? (
          <span className="font-mono text-sm text-muted-foreground">
            The desk checks the stop and targets against mark when you re-plan.
          </span>
        ) : refused ? (
          <span className="font-mono text-sm text-warn">
            {refused.rule} · {refused.message}
          </span>
        ) : plan ? (
          <>
            <Row label={form.entryType === "trail" && mode === "enter" ? "Entry, at the trigger now" : "Entry"}>
              {formatPrice(plan.entry)}
            </Row>
            <Row label="Stop" tone="ask">
              {formatPrice(plan.stop)} ({signedPct(plan.stop_pct)})
            </Row>
            <Row label="R">{formatPrice(plan.r)}</Row>
            <Row label="Size">
              {formatSize(plan.size)} {market.symbol}
            </Row>
            <Row label="Risk at the stop">
              ${Number(parseFloat(plan.risk_usd).toFixed(2))}
              {plan.risk_pct != null ? ` = ${Number(parseFloat(plan.risk_pct).toFixed(2))}% of equity` : ""}
            </Row>
            {plan.targets.map((t) => (
              <Row
                key={t.index}
                label={`TP${t.index} · ${Number(parseFloat(t.pct).toFixed(2))}% · ${t.order === "trail" ? `trail ${trailedBy(t)}` : t.order === "trigger" ? "trigger" : "limit"}`}
                tone="bid"
              >
                {formatPrice(t.price)} ({signedPct(t.move_pct)}, {rLabel(t.r)}) · {formatSize(t.qty)}
              </Row>
            ))}
            {parseFloat(plan.runner) > 0 && <Row label="Runner">{formatSize(plan.runner)}</Row>}
            {(plan.steps ?? []).map((step) => {
              const gap = step.to === "breakeven" ? null : stepGapPct(plan, step.after, step.price);
              return (
                <Row key={step.after} label={`At TP${step.after}, stop to`}>
                  {formatPrice(step.price)} ({stepTargetLabel(step.to)}
                  {gap ? `, ${gap} from TP${step.after}` : ""})
                </Row>
              );
            })}
            {plan.warnings.map((w) => (
              <span key={w} className="font-mono text-xs text-warn">
                {w}
              </span>
            ))}
            {replaces && <span className="font-mono text-xs text-warn">{replaces}</span>}
          </>
        ) : (
          <span className="font-mono text-sm text-muted-foreground">Drawing the plan…</span>
        )}
      </div>

      <DialogFooter className="gap-2 sm:justify-end">
        <Button type="button" variant="ghost" disabled={sending} onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          type="button"
          variant={long ? "buy" : "sell"}
          disabled={!canSend}
          onClick={() => void send()}
        >
          {replan ? "Re-plan" : mode === "attach" ? "Attach" : long ? "Plan long" : "Plan short"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
