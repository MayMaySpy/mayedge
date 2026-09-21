import { tokenIconUrl } from "@/lib/marketPicker";
import { cn } from "@/lib/utils";
import { useState } from "react";

export function TokenMark({
  symbol,
  className,
}: {
  symbol: string;
  className?: string;
}) {
  return <TokenMarkInner key={symbol} symbol={symbol} className={className} />;
}

function TokenMarkInner({
  symbol,
  className,
}: {
  symbol: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span
        className={cn(
          "inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-elevated font-sans text-xs font-medium text-muted-foreground",
          className
        )}
        aria-hidden
      >
        {symbol.slice(0, 1)}
      </span>
    );
  }

  return (
    <img
      src={tokenIconUrl(symbol)}
      alt=""
      className={cn("size-5 shrink-0 rounded-full object-cover", className)}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
