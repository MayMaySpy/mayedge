import { toast } from "sonner";
import { FillNotice } from "@/components/desk/FillNotice";
import { orderNotice, type NoticeTone, type OrderNoticeInput } from "@/lib/orderNotice";

export function notifyDesk(opts: {
  title: string;
  description?: string;
  tone: NoticeTone;
  symbol?: string;
  duration?: number;
}) {
  toast.custom(
    () => (
      <FillNotice
        title={opts.title}
        description={opts.description ?? ""}
        tone={opts.tone}
        symbol={opts.symbol}
      />
    ),
    { duration: opts.duration ?? 3800, unstyled: true, className: "w-[var(--width)]" }
  );
}

export function notifyOrder(input: OrderNoticeInput) {
  const n = orderNotice(input);
  notifyDesk({ ...n, symbol: input.symbol });
}

export function notifyOk(title: string, description?: string, symbol?: string) {
  notifyDesk({ title, description, tone: "ok", symbol });
}

export function notifyErr(message: string, title = "Failed") {
  notifyDesk({ title, description: message, tone: "err" });
}

export function notifyWarn(title: string, description?: string, symbol?: string) {
  notifyDesk({ title, description, tone: "warn", symbol });
}
