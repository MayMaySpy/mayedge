import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, FieldContent, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import { useAutoKill, setAutoKill as applyAutoKill } from "@/lib/liveData";
import { notifyErr, notifyOk } from "@/lib/notify";
import { formatPrice } from "@/lib/utils";

interface AutoKillSectionProps {
  tradingEnabled: boolean;
}

function parseUsdInput(raw: string): number | null {
  const t = raw.trim();
  if (!t) return null;
  const n = Number(t);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

export function AutoKillSection({ tradingEnabled }: AutoKillSectionProps) {
  const live = useAutoKill();
  const [lossInput, setLossInput] = useState("");
  const [profitInput, setProfitInput] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setLossInput(live.loss_usd != null ? String(live.loss_usd) : "");
    setProfitInput(live.profit_usd != null ? String(live.profit_usd) : "");
  }, [live.loss_usd, live.profit_usd]);

  const save = async (armed: boolean) => {
    const loss_usd = parseUsdInput(lossInput);
    const profit_usd = parseUsdInput(profitInput);
    if (armed && loss_usd == null && profit_usd == null) {
      notifyErr("Set a loss floor or profit target");
      return;
    }
    setBusy(true);
    try {
      const res = await api.setAutoKill({
        armed,
        loss_usd,
        profit_usd,
      });
      applyAutoKill(res);
      notifyOk(armed ? "Auto kill armed" : "Auto kill disarmed");
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Auto kill update failed");
    } finally {
      setBusy(false);
    }
  };

  const lastFired =
    live.fired_at != null
      ? `${live.fired_reason ?? "trigger"} · ${live.fired_upnl != null ? formatPrice(live.fired_upnl, 2) : "—"} · ${live.last_kill_status ?? "—"}`
      : null;

  return (
    <div className="space-y-3">
      <Separator />
      <p className="text-sm text-muted-foreground">
        When total uPnL crosses a USD threshold, stop algos, cancel orders, and flatten once. Then
        disarm.
      </p>
      <FieldGroup>
        <div className="grid grid-cols-2 gap-3">
          <Field>
            <FieldLabel>Loss floor (USD)</FieldLabel>
            <FieldContent>
              <Input
                type="text"
                inputMode="decimal"
                placeholder="500"
                disabled={!tradingEnabled || busy || live.armed}
                value={lossInput}
                onChange={(e) => setLossInput(e.target.value)}
              />
            </FieldContent>
          </Field>
          <Field>
            <FieldLabel>Profit target (USD)</FieldLabel>
            <FieldContent>
              <Input
                type="text"
                inputMode="decimal"
                placeholder="1000"
                disabled={!tradingEnabled || busy || live.armed}
                value={profitInput}
                onChange={(e) => setProfitInput(e.target.value)}
              />
            </FieldContent>
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          {live.armed ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!tradingEnabled || busy}
              onClick={() => void save(false)}
            >
              Disarm
            </Button>
          ) : (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={!tradingEnabled || busy}
              onClick={() => void save(true)}
            >
              Arm auto kill
            </Button>
          )}
        </div>
        {lastFired ? (
          <p className="font-mono text-sm text-muted-foreground">Last fired: {lastFired}</p>
        ) : null}
      </FieldGroup>
    </div>
  );
}
