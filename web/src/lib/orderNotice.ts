export type NoticeTone = "bid" | "ask" | "ok" | "warn" | "err";

export type OrderNoticeInput = {
  kind: "market" | "limit" | "twap" | "chase" | "leverage" | "fill" | "desk";
  side?: "buy" | "sell";
  size?: string;
  symbol?: string;
  price?: string;
  status?: "sent" | "active" | "paused" | "error" | "filled";
  note?: string;
  title?: string;
};

function sideWord(side?: "buy" | "sell") {
  if (side === "buy") return "Buy";
  if (side === "sell") return "Sell";
  return "";
}

function leg(input: OrderNoticeInput): string {
  const core = [sideWord(input.side), input.size, input.symbol].filter(Boolean).join(" ");
  if (input.price) return core ? `${core} · ${input.price}` : input.price;
  return core;
}

export function orderNotice(input: OrderNoticeInput): {
  title: string;
  description: string;
  tone: NoticeTone;
} {
  if (input.status === "error") {
    const title = input.kind === "chase" ? "Chase failed" : input.title || "Order failed";
    return { title, description: input.note ?? "", tone: "err" };
  }
  const tone: NoticeTone = input.side === "sell" ? "ask" : input.side === "buy" ? "bid" : "ok";
  if (input.kind === "fill" || input.status === "filled") {
    return { title: "Filled", description: leg(input), tone };
  }
  if (input.kind === "desk") {
    return { title: input.title || "Done", description: input.note ?? leg(input), tone: "ok" };
  }
  if (input.kind === "leverage") {
    return { title: "Leverage set", description: input.note ?? "", tone: "ok" };
  }
  if (input.kind === "chase") {
    if (input.status === "paused") {
      return {
        title: "Chase paused",
        description: [leg(input), input.note].filter(Boolean).join(" · "),
        tone: "warn",
      };
    }
    return { title: "Chase started", description: leg(input), tone };
  }
  if (input.kind === "twap") {
    if (input.status === "active") {
      return { title: "TWAP started", description: leg(input), tone };
    }
    return { title: "TWAP sent", description: leg(input), tone };
  }
  return { title: "Order sent", description: leg(input), tone };
}
