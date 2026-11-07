import type { SetupKind, SetupRow } from "@/lib/api";

/** docs/setup-rules.md X1–X6, as the board names them. */
const SETUP_NAME: Record<SetupKind, string> = {
  oi_price: "OI without price",
  funding: "Funding stretched",
  board: "Against the board",
  coil: "Coiled at a level",
  reclaim: "Reclaim",
  flush: "Liquidation flush",
};

export function setupName(kind: string): string {
  return SETUP_NAME[kind as SetupKind] ?? kind;
}

/** The arrow a row shows. A Setup with no direction shows none. */
export function setupArrow(row: Pick<SetupRow, "direction">): string {
  if (row.direction === "up") return "↑";
  if (row.direction === "down") return "↓";
  return "";
}
