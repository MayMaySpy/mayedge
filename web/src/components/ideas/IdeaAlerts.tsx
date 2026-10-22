import { useEffect, useState } from "react";
import { Bell, Repeat, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ApiError, api } from "@/lib/api";
import type { Idea, IdeaAlert, IdeaAlertBody } from "@/lib/api.gen";
import {
  ALERTS_PER_IDEA,
  alertDistancePct,
  alertWhat,
  alertsPaused,
  hasPlanPrice,
} from "@/lib/ideaAlerts";
import { price } from "@/lib/journalFormat";
import { utcDateTime } from "@/lib/utcTime";

type Kind = IdeaAlertBody["kind"];
type Way = NonNullable<IdeaAlertBody["direction"]> | "auto";

function message(e: unknown, fallback: string): string {
  return e instanceof ApiError || e instanceof Error ? e.message : fallback;
}

/** Whether a fired alert also reaches Telegram. Unknown until the desk answers. */
function usePushOn(): boolean | null {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    api
      .pushStatus()
      .then((status) => {
        if (live) setOn(status.enabled);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  return on;
}

export function IdeaAlerts({
  idea,
  last,
  alerts,
  onChanged,
}: {
  idea: Idea;
  last: number | null;
  alerts: IdeaAlert[];
  onChanged: () => Promise<void>;
}) {
  const pushOn = usePushOn();
  const [kind, setKind] = useState<Kind>("level");
  const [value, setValue] = useState("");
  const [way, setWay] = useState<Way>("auto");
  const [repeat, setRepeat] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const full = alerts.length >= ALERTS_PER_IDEA;

  const pickKind = (next: Kind) => {
    setKind(next);
    setWay(next === "level" ? "auto" : "either");
    setValue("");
    setError("");
  };

  const run = async (work: () => Promise<unknown>, fallback: string) => {
    setBusy(true);
    setError("");
    try {
      await work();
      await onChanged();
      return true;
    } catch (e) {
      setError(message(e, fallback));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    const text = value.trim();
    if (!text) {
      setError(kind === "level" ? "Type the price." : "Type the percent.");
      return;
    }
    const body: IdeaAlertBody = {
      kind,
      direction: way === "auto" ? null : way,
      repeat,
      note: note.trim(),
      ...(kind === "level" ? { price: text } : { pct: text }),
    };
    const ok = await run(() => api.ideaAlertCreate(idea.id, body), "Not saved, retry");
    if (ok) {
      setValue("");
      setNote("");
    }
  };

  const fromPlan = () =>
    run(async () => {
      const made = await api.ideaAlertsFromPlan(idea.id);
      if (made.alerts.length === 0) setError("Every Plan price is already watched, or Last is on it.");
    }, "Not saved, retry");

  return (
    <div className="flex flex-col gap-3 pt-2">
      {pushOn === false ? (
        <p className="rounded-[4px] border-[0.5px] border-warn/40 p-2 text-warn" role="status">
          Telegram is off, so a fired alert only toasts on the desk and logs here. Set TELEGRAM_CHAT_ID in
          backend/.env and restart the desk to push.
        </p>
      ) : null}
      {alertsPaused(idea) ? (
        <p className="text-muted-foreground">
          This Idea is {idea.status === "closed" ? "Closed" : "Dropped"}. Its alerts wait until it is reopened.
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            type="single"
            size="sm"
            value={kind}
            aria-label="Alert kind"
            onValueChange={(next) => {
              if (next === "level" || next === "move" || next === "day") pickKind(next);
            }}
          >
            <ToggleGroupItem value="level" className="h-6 px-2 text-xs">
              Level
            </ToggleGroupItem>
            <ToggleGroupItem value="move" className="h-6 px-2 text-xs">
              Move
            </ToggleGroupItem>
            <ToggleGroupItem value="day" className="h-6 px-2 text-xs">
              Day
            </ToggleGroupItem>
          </ToggleGroup>
          <Input
            aria-label={kind === "level" ? "Alert price" : "Alert percent"}
            className="h-6 w-28 font-mono"
            inputMode="decimal"
            placeholder={kind === "level" ? "Price" : "%"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void add();
              }
            }}
          />
          {kind === "level" && last != null ? (
            <Button type="button" variant="ghost" size="sm" className="h-6 px-2" onClick={() => setValue(String(last))}>
              Use Last
            </Button>
          ) : null}
          <Select value={way} onValueChange={(next) => setWay(next as Way)}>
            <SelectTrigger className="h-6" aria-label="Alert direction">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {kind === "level" ? (
                <>
                  <SelectItem value="auto">From Last</SelectItem>
                  <SelectItem value="above">Above</SelectItem>
                  <SelectItem value="below">Below</SelectItem>
                </>
              ) : (
                <>
                  <SelectItem value="either">Either way</SelectItem>
                  <SelectItem value="up">Up</SelectItem>
                  <SelectItem value="down">Down</SelectItem>
                </>
              )}
            </SelectContent>
          </Select>
          <ToggleGroup
            type="single"
            size="sm"
            value={repeat ? "repeat" : "once"}
            aria-label="Alert repeat"
            onValueChange={(next) => {
              if (next) setRepeat(next === "repeat");
            }}
          >
            <ToggleGroupItem value="once" className="h-6 px-2 text-xs">
              Once
            </ToggleGroupItem>
            <ToggleGroupItem value="repeat" className="h-6 px-2 text-xs">
              Repeat
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Alert note"
            className="h-6 min-w-0 flex-1"
            maxLength={120}
            placeholder="Note for the push (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <Button type="button" size="sm" className="h-7" disabled={busy || full} onClick={() => void add()}>
            <Bell data-icon="inline-start" />
            Add alert
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7"
            disabled={busy || full || !hasPlanPrice(idea)}
            title={hasPlanPrice(idea) ? "A Level alert at the zone, the stop and each target" : "Write a Plan first"}
            onClick={() => void fromPlan()}
          >
            Alert on my plan
          </Button>
        </div>
        <p className="text-muted-foreground">
          {kind === "level"
            ? "Fires when Last reaches the price. From Last picks above or below for you."
            : kind === "move"
              ? "Fires when Last moves this far from where it is now."
              : "Fires when the Daily Change reaches this percent."}{" "}
          {repeat ? "Repeat arms it again 15 minutes after it fires." : "Once fires one time; re-arm it after."}
        </p>
        {full ? <p className="text-muted-foreground">An Idea holds at most {ALERTS_PER_IDEA} alerts.</p> : null}
        {error ? <p className="text-ask">{error}</p> : null}
      </div>

      {alerts.length === 0 ? (
        <p className="text-muted-foreground">No alerts yet. They check every 2 seconds while the desk runs.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {alerts.map((alert) => (
            <AlertRow
              key={alert.id}
              alert={alert}
              last={last}
              busy={busy}
              onRearm={() => void run(() => api.ideaAlertRearm(alert.id), "Not re-armed, retry")}
              onDelete={() => void run(() => api.ideaAlertDelete(alert.id), "Not deleted, retry")}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function AlertRow({
  alert,
  last,
  busy,
  onRearm,
  onDelete,
}: {
  alert: IdeaAlert;
  last: number | null;
  busy: boolean;
  onRearm: () => void;
  onDelete: () => void;
}) {
  const away = alertDistancePct(alert, last);
  const fired = alert.status === "fired";
  return (
    <li className="flex items-start gap-2 border-b-[0.5px] border-rule pb-2">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono">{alertWhat(alert)}</span>
          {alert.label ? <span className="text-muted-foreground">{alert.label}</span> : null}
          <Badge variant={fired ? "warn" : "outline"}>{fired ? "Fired" : "Armed"}</Badge>
          {alert.repeat ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground" title="Re-arms 15 minutes after it fires">
              <Repeat className="size-3" aria-hidden />
              Repeat
            </span>
          ) : null}
          {away != null ? (
            <span className="font-mono text-muted-foreground">{`${Math.abs(away).toFixed(2)}% away`}</span>
          ) : null}
        </div>
        {alert.fired_at != null ? (
          <span className="font-mono text-muted-foreground">
            {fired ? "Fired" : "Last fired"} {utcDateTime(alert.fired_at)} UTC
            {alert.fired_last ? ` at ${price(alert.fired_last)}` : ""}
            {alert.fires > 1 ? ` · ${alert.fires}×` : ""}
          </span>
        ) : null}
        {alert.note ? <span className="font-sans">{alert.note}</span> : null}
      </div>
      {fired && !alert.repeat ? (
        <Button type="button" variant="ghost" size="sm" className="h-6 px-2" disabled={busy} onClick={onRearm}>
          Re-arm
        </Button>
      ) : null}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-6 w-6 px-0"
        aria-label={`Delete alert ${alertWhat(alert)}`}
        disabled={busy}
        onClick={onDelete}
      >
        <X className="size-3.5" />
      </Button>
    </li>
  );
}
