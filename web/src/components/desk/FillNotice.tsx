import { TokenMark } from "@/components/desk/TokenMark";
import { cn } from "@/lib/utils";
import type { NoticeTone } from "@/lib/orderNotice";

const rail: Record<NoticeTone, string> = {
  bid: "bg-bid",
  ask: "bg-ask",
  ok: "bg-muted",
  warn: "bg-warn",
  err: "bg-ask",
};

const edge: Record<NoticeTone, string> = {
  bid: "border-bid/50",
  ask: "border-ask/50",
  ok: "border-rule",
  warn: "border-warn/50",
  err: "border-ask/50",
};

export function FillNotice({
  title,
  description,
  tone,
  symbol,
}: {
  title: string;
  description: string;
  tone: NoticeTone;
  symbol?: string;
}) {
  return (
    <div
      className={cn(
        "flex w-full items-stretch gap-2.5 rounded-md border bg-elevated py-2 pr-3 pl-2.5 shadow-[0_8px_24px_rgba(0,0,0,0.55)]",
        edge[tone]
      )}
    >
      <span className={cn("w-0.5 shrink-0 self-stretch rounded-full", rail[tone])} />
      {symbol ? <TokenMark symbol={symbol} className="mt-0.5 size-4" /> : null}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-xs font-medium text-text">{title}</p>
        {description ? (
          <p className="font-mono text-[11px] leading-snug wrap-break-word text-muted">{description}</p>
        ) : null}
      </div>
    </div>
  );
}
